"""Auto-detect and launch ngrok/cloudflared tunnels for plan sharing."""

from __future__ import annotations

import asyncio
import shutil
import re


async def detect_and_start_tunnel(port: int) -> str | None:
    """Try to start a tunnel to the given local port.

    Checks for ngrok first, then cloudflared. Returns the public URL
    if a tunnel was established, or None if no tunnel tool is available.
    """
    # Try ngrok first
    if shutil.which("ngrok"):
        return await _start_ngrok(port)

    # Try cloudflared
    if shutil.which("cloudflared"):
        return await _start_cloudflared(port)

    return None


_tunnel_process: asyncio.subprocess.Process | None = None


async def _start_ngrok(port: int) -> str | None:
    """Start an ngrok tunnel and return the public URL."""
    global _tunnel_process
    try:
        _tunnel_process = await asyncio.create_subprocess_exec(
            "ngrok",
            "http",
            str(port),
            "--log",
            "stdout",
            "--log-format",
            "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # Read lines until we find the URL (with timeout)
        assert _tunnel_process.stdout is not None
        try:
            async with asyncio.timeout(10):
                while True:
                    line = await _tunnel_process.stdout.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="ignore")
                    # ngrok JSON log contains url field
                    match = re.search(r'"url"\s*:\s*"(https?://[^"]+)"', text)
                    if match:
                        return match.group(1)
        except TimeoutError:
            pass
    except Exception:
        pass
    return None


async def _start_cloudflared(port: int) -> str | None:
    """Start a cloudflared quick tunnel and return the public URL."""
    global _tunnel_process
    try:
        _tunnel_process = await asyncio.create_subprocess_exec(
            "cloudflared",
            "tunnel",
            "--url",
            f"http://localhost:{port}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # cloudflared prints the URL to stderr
        assert _tunnel_process.stderr is not None
        try:
            async with asyncio.timeout(15):
                while True:
                    line = await _tunnel_process.stderr.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="ignore")
                    match = re.search(r"(https://[^\s]+\.trycloudflare\.com)", text)
                    if match:
                        return match.group(1)
        except TimeoutError:
            pass
    except Exception:
        pass
    return None


async def stop_tunnel() -> None:
    """Stop any running tunnel process."""
    global _tunnel_process
    if _tunnel_process is not None:
        try:
            _tunnel_process.terminate()
            await asyncio.wait_for(_tunnel_process.wait(), timeout=5)
        except Exception:
            try:
                _tunnel_process.kill()
            except Exception:
                pass
        _tunnel_process = None
