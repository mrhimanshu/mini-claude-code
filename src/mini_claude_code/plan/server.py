"""Embedded aiohttp web server for plan sharing and collaborative editing.

Provides REST API endpoints and WebSocket for real-time collaboration.
Runs as an asyncio background task alongside the REPL.

API:
    GET  /              -> serves the interactive HTML SPA
    GET  /api/plan      -> returns the full plan JSON
    PUT  /api/plan/content -> update plan content
    POST /api/plan/annotate -> add an annotation
    POST /api/plan/annotate/resolve -> resolve an annotation
    POST /api/plan/approve -> approve the plan
    POST /api/plan/reject  -> reject the plan
    WS   /ws            -> real-time collaboration
"""

from __future__ import annotations

import asyncio
import json
import socket
from typing import Any

import aiohttp
from aiohttp import web

from mini_claude_code.plan.manager import PLAN_MANAGER, Annotation, Edit
from mini_claude_code.plan.templates import PLAN_EDITOR_HTML
from mini_claude_code.plan.tunnel import detect_and_start_tunnel, stop_tunnel


class PlanServer:
    """Embedded async web server for plan sharing and review."""

    def __init__(self) -> None:
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._ws_clients: dict[web.WebSocketResponse, str] = {}
        self._port: int = 0
        self._tunnel_url: str | None = None
        self._running = False

    @property
    def port(self) -> int:
        return self._port

    @property
    def local_url(self) -> str:
        return f"http://localhost:{self._port}"

    @property
    def share_url(self) -> str:
        return self._tunnel_url or self.local_url

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self, port: int = 0) -> str:
        if self._running:
            return self.share_url

        self._app = web.Application()
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/api/plan", self._handle_get_plan)
        self._app.router.add_put("/api/plan/content", self._handle_update_content)
        self._app.router.add_post("/api/plan/annotate", self._handle_annotate)
        self._app.router.add_post("/api/plan/annotate/resolve", self._handle_resolve)
        self._app.router.add_post("/api/plan/approve", self._handle_approve)
        self._app.router.add_post("/api/plan/reject", self._handle_reject)
        self._app.router.add_get("/ws", self._handle_websocket)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        if port == 0:
            port = _find_free_port()
        self._port = port

        self._site = web.TCPSite(self._runner, "0.0.0.0", self._port)
        await self._site.start()
        self._running = True

        PLAN_MANAGER.register_update_callback(self._on_plan_update)
        self._tunnel_url = await detect_and_start_tunnel(self._port)

        return self.share_url

    async def stop(self) -> None:
        if not self._running:
            return
        PLAN_MANAGER.unregister_update_callback(self._on_plan_update)
        for ws_client in list(self._ws_clients.keys()):
            try:
                await ws_client.close()
            except Exception:
                pass
        self._ws_clients.clear()
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()
        await stop_tunnel()
        self._running = False

    # -- HTTP handlers -----------------------------------------------------

    async def _handle_index(self, request: web.Request) -> web.Response:
        return web.Response(text=PLAN_EDITOR_HTML, content_type="text/html")

    async def _handle_get_plan(self, request: web.Request) -> web.Response:
        plan = PLAN_MANAGER.current_plan
        if plan is None:
            return web.json_response({"error": "No plan available"}, status=404)
        return web.json_response(plan.to_dict())

    async def _handle_update_content(self, request: web.Request) -> web.Response:
        data = await request.json()
        content = data.get("content", "")
        user = data.get("user", "web-user")
        await PLAN_MANAGER.update_content(content, user=user)
        return web.json_response({"ok": True})

    async def _handle_annotate(self, request: web.Request) -> web.Response:
        data = await request.json()
        ann = Annotation(
            id=data.get("id", ""),
            user=data.get("user", "web-user"),
            text=data.get("text", ""),
            quote=data.get("quote", ""),
            range_start=data.get("range_start", 0),
            range_end=data.get("range_end", 0),
        )
        await PLAN_MANAGER.add_annotation(ann)
        return web.json_response({"ok": True})

    async def _handle_resolve(self, request: web.Request) -> web.Response:
        data = await request.json()
        ann_id = data.get("annotation_id", "")
        ok = await PLAN_MANAGER.resolve_annotation(ann_id)
        return web.json_response({"ok": ok})

    async def _handle_approve(self, request: web.Request) -> web.Response:
        data = await request.json()
        user = data.get("user", "web-user")
        fully_approved = await PLAN_MANAGER.record_approval(user)
        status = PLAN_MANAGER.get_approval_status()
        if fully_approved:
            await self._broadcast(
                {"type": "all_approved", "approved_by": status["approved_users"]}
            )
        else:
            await self._broadcast(
                {"type": "user_approved", "user": user, "status": status}
            )
        return web.json_response({"ok": True, "status": status})

    async def _handle_reject(self, request: web.Request) -> web.Response:
        data = await request.json()
        user = data.get("user", "web-user")
        reason = data.get("reason", "")
        await PLAN_MANAGER.reject(reason=reason, user=user)
        await self._broadcast({"type": "rejected", "user": user, "reason": reason})
        return web.json_response({"ok": True, "status": "rejected"})

    # -- WebSocket handler -------------------------------------------------

    def _unique_ws_users(self) -> set[str]:
        """Return the set of unique usernames across all WS connections."""
        return set(self._ws_clients.values())

    async def _sync_connected_users(self) -> bool:
        """Push the current WS user set into PlanManager.
        Returns True if this caused full approval (e.g. a non-approver left)."""
        users = self._unique_ws_users()
        fully_approved = await PLAN_MANAGER.update_connected_users(users)
        # Broadcast approval status to all clients so they update their UI
        status = PLAN_MANAGER.get_approval_status()
        await self._broadcast({"type": "approval_status", "status": status})
        if fully_approved:
            await self._broadcast(
                {
                    "type": "all_approved",
                    "approved_by": status["approved_users"],
                }
            )
        return fully_approved

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        username = request.query.get("user", "anonymous")
        self._ws_clients[ws] = username

        # Notify others and sync connected users
        await self._broadcast({"type": "user_join", "user": username}, exclude=ws)
        users = list(self._unique_ws_users())
        await self._send(ws, {"type": "users_list", "users": users})

        # Send current plan state + approval status to the new client
        if PLAN_MANAGER.current_plan:
            await self._send(
                ws,
                {
                    "type": "plan_update",
                    "plan": PLAN_MANAGER.current_plan.to_dict(),
                },
            )
        status = PLAN_MANAGER.get_approval_status()
        await self._send(ws, {"type": "approval_status", "status": status})

        # Update connected users in manager (may affect approval threshold)
        await self._sync_connected_users()

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self._handle_ws_message(data, ws, username)
                    except json.JSONDecodeError:
                        pass
                elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                    break
        finally:
            del self._ws_clients[ws]
            await self._broadcast({"type": "user_leave", "user": username})
            # Re-sync connected users (leaving user removed from required set)
            await self._sync_connected_users()

        return ws

    async def _handle_ws_message(
        self, data: dict[str, Any], sender: web.WebSocketResponse, username: str
    ) -> None:
        msg_type = data.get("type")

        if msg_type == "content_update":
            content = data.get("content", "")
            edit_data = data.get("edit")
            await PLAN_MANAGER.update_content(content, user=username)
            broadcast_msg: dict[str, Any] = {
                "type": "content_update",
                "content": content,
                "user": username,
            }
            if edit_data:
                broadcast_msg["edit"] = edit_data
            await self._broadcast(broadcast_msg, exclude=sender)

        elif msg_type == "annotation_add":
            ann_data = data.get("annotation", {})
            if ann_data:
                ann = Annotation(
                    id=ann_data.get("id", ""),
                    user=ann_data.get("user", username),
                    text=ann_data.get("text", ""),
                    quote=ann_data.get("quote", ""),
                    range_start=ann_data.get("range_start", 0),
                    range_end=ann_data.get("range_end", 0),
                )
                await PLAN_MANAGER.add_annotation(ann)
                await self._broadcast(
                    {
                        "type": "annotation_add",
                        "annotation": ann_data,
                        "user": username,
                    },
                    exclude=sender,
                )

        elif msg_type == "annotation_resolve":
            ann_id = data.get("annotation_id", "")
            if ann_id:
                await PLAN_MANAGER.resolve_annotation(ann_id)
                await self._broadcast(
                    {
                        "type": "annotation_resolve",
                        "annotation_id": ann_id,
                        "user": username,
                    },
                    exclude=sender,
                )

        elif msg_type == "approve":
            user = data.get("user", username)
            fully_approved = await PLAN_MANAGER.record_approval(user)
            status = PLAN_MANAGER.get_approval_status()
            if fully_approved:
                await self._broadcast(
                    {
                        "type": "all_approved",
                        "approved_by": status["approved_users"],
                    }
                )
            else:
                await self._broadcast(
                    {
                        "type": "user_approved",
                        "user": user,
                        "status": status,
                    }
                )

        elif msg_type == "request_changes":
            user = data.get("user", username)
            reason = data.get("reason", "")
            ann_dict = None
            if reason:
                ann = Annotation(
                    user=user,
                    text=f"Change requested: {reason}",
                    quote="",
                    range_start=0,
                    range_end=len(PLAN_MANAGER.current_plan.content)
                    if PLAN_MANAGER.current_plan
                    else 0,
                )
                await PLAN_MANAGER.add_annotation(ann)
                ann_dict = ann.to_dict()
            # Set status to changes_requested (non-terminal — does NOT fire rejection event)
            async with PLAN_MANAGER._lock:
                if PLAN_MANAGER.current_plan:
                    PLAN_MANAGER.current_plan.status = "changes_requested"
            await self._broadcast(
                {
                    "type": "changes_requested",
                    "user": user,
                    "reason": reason,
                    "annotation": ann_dict,
                }
            )

        elif msg_type == "rejected":
            user = data.get("user", username)
            reason = data.get("reason", "")
            await PLAN_MANAGER.reject(reason=reason, user=user)
            await self._broadcast({"type": "rejected", "user": user, "reason": reason})

    # -- Broadcast ---------------------------------------------------------

    async def _send(self, ws: web.WebSocketResponse, data: dict) -> None:
        try:
            await ws.send_json(data)
        except Exception:
            pass

    async def _broadcast(
        self, data: dict, exclude: web.WebSocketResponse | None = None
    ) -> None:
        for ws_client in list(self._ws_clients.keys()):
            if ws_client is not exclude and not ws_client.closed:
                await self._send(ws_client, data)

    async def _on_plan_update(self) -> None:
        """Called when plan is updated locally (e.g. from CLI /approve)."""
        if PLAN_MANAGER.current_plan:
            await self._broadcast(
                {
                    "type": "plan_update",
                    "plan": PLAN_MANAGER.current_plan.to_dict(),
                }
            )


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


PLAN_SERVER = PlanServer()
