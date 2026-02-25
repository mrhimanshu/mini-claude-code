---
description: Code review checklist and best practices
---

# Code Review Skill

When reviewing code, follow this checklist:

1. **Correctness**: Does the code do what it claims?
2. **Edge cases**: Are boundary conditions handled?
3. **Error handling**: Are errors caught and reported properly?
4. **Security**: Any injection, path traversal, or secret exposure?
5. **Performance**: Obvious N+1 queries, unnecessary loops, or memory leaks?
6. **Readability**: Clear names, minimal nesting, appropriate comments?
7. **Testing**: Are there tests? Do they cover the happy path and error cases?

Provide feedback in this format:
- **File**: path/to/file.py:line_number
- **Severity**: critical | warning | suggestion
- **Issue**: What's wrong
- **Fix**: How to fix it
