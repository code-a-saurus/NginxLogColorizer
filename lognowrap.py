#!/usr/bin/env python3
# This is free and unencumbered software released into the public domain.
#
# Anyone is free to copy, modify, publish, use, compile, sell, or
# distribute this software, either in source code form or as a compiled
# binary, for any purpose, commercial or non-commercial, and by any
# means.
#
# In jurisdictions that recognize copyright laws, the author or authors
# of this software dedicate any and all copyright interest in the
# software to the public domain. We make this dedication for the benefit
# of the public at large and to the detriment of our heirs and
# successors. We intend this dedication to be an overt act of
# relinquishment in perpetuity of all present and future rights to this
# software under copyright law.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR
# OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
# ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.
#
# For more information, please refer to <http://unlicense.org/>

"""
Display ANSI-colored input without line wrapping.

A lightweight display wrapper that accepts ANSI-colored text from stdin and
displays it with horizontal scrolling instead of line wrapping. Perfect for
viewing long, pre-formatted log lines in real-time.

Usage:
    tail -f /var/log/nginx/access.log | ./colorize-nginx-logs.py | lognowrap
    cat access.log | ./colorize-nginx-logs.py | lognowrap

Features:
  - No line wrapping (horizontal scrolling with arrow keys)
  - Preserves all ANSI color codes and formatting
  - Real-time streaming (no buffering delays)
  - Handles terminal resize (SIGWINCH)
  - Minimal memory footprint (displays only visible screen)

Controls:
  Left Arrow  - Scroll left
  Right Arrow - Scroll right
  Ctrl+C      - Exit

This tool does ONE thing: display already-formatted ANSI text without wrapping.
It does NOT parse logs, colorize output, or modify input in any way.
"""

import collections
import fcntl
import os
import selectors
import signal
import sys
import termios
import tty
import unicodedata

try:
    import wcwidth  # type: ignore
except Exception:
    wcwidth = None

ESC = "\x1b"
MAX_LINE_BYTES = 1024 * 1024  # Safety cap for malformed or unbounded input.


def _set_nonblocking(fd):
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)


def _consume_ansi(line, start):
    if start + 1 >= len(line):
        return line[start], start + 1
    nxt = line[start + 1]
    if nxt == "[":
        i = start + 2
        while i < len(line):
            c = line[i]
            if "@" <= c <= "~":
                i += 1
                return line[start:i], i
            i += 1
        return line[start:], len(line)
    if nxt == "]":
        i = start + 2
        while i < len(line):
            if line[i] == "\x07":
                i += 1
                return line[start:i], i
            if line[i] == ESC and i + 1 < len(line) and line[i + 1] == "\\":
                i += 2
                return line[start:i], i
            i += 1
        return line[start:], len(line)
    if nxt in "()#%":
        if start + 2 < len(line):
            return line[start:start + 3], start + 3
        return line[start:], len(line)
    return line[start:start + 2], start + 2


def _iter_tokens(line):
    i = 0
    while i < len(line):
        if line[i] == ESC:
            seq, i = _consume_ansi(line, i)
            yield True, seq
        else:
            yield False, line[i]
            i += 1


def _char_width(ch):
    if wcwidth is None:
        code = ord(ch)
        if code < 0x20 or (0x7f <= code < 0xa0):
            return 0
        if unicodedata.combining(ch) or unicodedata.category(ch) == "Cf":
            return 0
        east = unicodedata.east_asian_width(ch)
        return 2 if east in ("W", "F") else 1
    width = wcwidth.wcwidth(ch)
    return 0 if width < 0 else width


def visible_width(line):
    width = 0
    for is_ansi, token in _iter_tokens(line):
        if is_ansi:
            continue
        width += _char_width(token)
    return width


def slice_ansi(line, start_col, width):
    if width <= 0:
        return ""
    pos = 0
    visible = 0
    started = False
    prefix = ""
    out = []
    for is_ansi, token in _iter_tokens(line):
        if is_ansi:
            if not started:
                prefix += token
            else:
                out.append(token)
            continue

        w = _char_width(token)
        if w <= 0:
            if started:
                out.append(token)
            continue

        if pos + w <= start_col:
            pos += w
            continue

        if not started:
            started = True
            if prefix:
                out.append(prefix)

        out.append(token)
        pos += w
        visible += w
        if visible >= width:
            break

    if not started:
        return ""
    out.append(ESC + "[0m")
    return "".join(out)


def render(lines, term_width, term_height, xoff, first=False):
    out = sys.stdout
    if first:
        out.write(ESC + "[2J")
    out.write(ESC + "[H")
    for idx in range(term_height):
        out.write(ESC + "[0m")
        out.write(ESC + "[2K")
        if idx < len(lines):
            out.write(slice_ansi(lines[idx], xoff, term_width))
        if idx < term_height - 1:
            out.write("\r\n")
    out.flush()


def parse_keys(buf):
    actions = []
    i = 0
    while i < len(buf):
        if buf[i] != 0x1b:
            if buf[i] == 0x03:
                actions.append("quit")
            i += 1
            continue

        if buf.startswith(b"\x1b[C", i):
            actions.append("right")
            i += 3
            continue
        if buf.startswith(b"\x1b[D", i):
            actions.append("left")
            i += 3
            continue
        if buf.startswith(b"\x1bOC", i):
            actions.append("right")
            i += 3
            continue
        if buf.startswith(b"\x1bOD", i):
            actions.append("left")
            i += 3
            continue

        if i + 1 < len(buf) and buf[i + 1] == 0x5b:
            j = i + 2
            while j < len(buf) and not (0x40 <= buf[j] <= 0x7e):
                j += 1
            if j < len(buf):
                final = buf[j:j + 1]
                if final == b"C":
                    actions.append("right")
                elif final == b"D":
                    actions.append("left")
                i = j + 1
                continue
            break

        i += 1

    return actions, buf[i:]


class TtyMode:
    def __init__(self, fd):
        self.fd = fd
        self.old = termios.tcgetattr(fd)

    def __enter__(self):
        tty.setcbreak(self.fd)
        return self

    def __exit__(self, exc_type, exc, tb):
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)


def get_term_size():
    try:
        size = os.get_terminal_size(sys.stdout.fileno())
    except OSError:
        return 80, 24
    return max(1, size.columns), max(1, size.lines)


def main():
    try:
        tty_fd = os.open("/dev/tty", os.O_RDONLY)
    except OSError:
        sys.stderr.write("lognowrap: /dev/tty is required for key input\n")
        return 1

    stdin_fd = sys.stdin.fileno()
    _set_nonblocking(stdin_fd)
    _set_nonblocking(tty_fd)

    sel = selectors.DefaultSelector()
    sel.register(stdin_fd, selectors.EVENT_READ, data="stdin")
    sel.register(tty_fd, selectors.EVENT_READ, data="tty")

    resize_flag = False

    wake_r = wake_w = None
    old_wakeup_fd = None
    use_wakeup = False

    try:
        wake_r, wake_w = os.pipe()
        _set_nonblocking(wake_r)
        _set_nonblocking(wake_w)
        old_wakeup_fd = signal.set_wakeup_fd(wake_w)
        signal.signal(signal.SIGWINCH, lambda signum, frame: None)
        sel.register(wake_r, selectors.EVENT_READ, data="signal")
        use_wakeup = True
    except Exception:
        if wake_r is not None:
            os.close(wake_r)
            wake_r = None
        if wake_w is not None:
            os.close(wake_w)
            wake_w = None
        if old_wakeup_fd is not None:
            signal.set_wakeup_fd(old_wakeup_fd)
            old_wakeup_fd = None

        def on_resize(signum, frame):
            nonlocal resize_flag
            resize_flag = True

        signal.signal(signal.SIGWINCH, on_resize)

    term_width, term_height = get_term_size()
    lines = collections.deque(maxlen=term_height)
    xoff = 0
    inbuf = b""
    keybuf = b""
    dirty = True
    first = True

    try:
        with TtyMode(tty_fd):
            while True:
                if resize_flag:
                    resize_flag = False
                    term_width, term_height = get_term_size()
                    lines = collections.deque(lines, maxlen=term_height)
                    dirty = True

                events = sel.select(timeout=0.1)
                for key, _ in events:
                    if key.data == "stdin":
                        while True:
                            try:
                                chunk = os.read(stdin_fd, 4096)
                            except BlockingIOError:
                                break
                            if not chunk:
                                if inbuf:
                                    line = inbuf.rstrip(b"\r")
                                    lines.append(line.decode("utf-8", "replace"))
                                    inbuf = b""
                                    dirty = True
                                if dirty:
                                    max_width = max((visible_width(l) for l in lines), default=0)
                                    max_xoff = max(0, max_width - term_width)
                                    xoff = min(xoff, max_xoff)
                                    render(list(lines), term_width, term_height, xoff, first=first)
                                return 0
                            inbuf += chunk
                            while len(inbuf) > MAX_LINE_BYTES:
                                prefix = inbuf[:MAX_LINE_BYTES]
                                newline = prefix.rfind(b"\n")
                                if newline != -1:
                                    for raw in prefix[:newline].split(b"\n"):
                                        line = raw.rstrip(b"\r")
                                        lines.append(line.decode("utf-8", "replace"))
                                    inbuf = inbuf[newline + 1:]
                                    dirty = True
                                else:
                                    line = prefix.rstrip(b"\r")
                                    lines.append(line.decode("utf-8", "replace"))
                                    inbuf = inbuf[MAX_LINE_BYTES:]
                                    dirty = True
                            parts = inbuf.split(b"\n")
                            for raw in parts[:-1]:
                                line = raw.rstrip(b"\r")
                                lines.append(line.decode("utf-8", "replace"))
                                dirty = True
                            inbuf = parts[-1]
                    elif key.data == "tty":
                        try:
                            data = os.read(tty_fd, 1024)
                        except BlockingIOError:
                            data = b""
                        if not data:
                            return 0
                        keybuf += data
                        actions, keybuf = parse_keys(keybuf)
                        for action in actions:
                            if action == "left":
                                xoff = max(0, xoff - 1)
                                dirty = True
                            elif action == "right":
                                max_width = max((visible_width(l) for l in lines), default=0)
                                max_xoff = max(0, max_width - term_width)
                                xoff = min(xoff + 1, max_xoff)
                                dirty = True
                            elif action == "quit":
                                return 0
                    elif key.data == "signal":
                        try:
                            os.read(wake_r, 1024)
                        except BlockingIOError:
                            pass
                        resize_flag = True

                if dirty:
                    max_width = max((visible_width(l) for l in lines), default=0)
                    max_xoff = max(0, max_width - term_width)
                    xoff = min(xoff, max_xoff)
                    render(list(lines), term_width, term_height, xoff, first=first)
                    first = False
                    dirty = False
    except KeyboardInterrupt:
        return 0
    finally:
        if use_wakeup and old_wakeup_fd is not None:
            signal.set_wakeup_fd(old_wakeup_fd)
        if wake_r is not None:
            os.close(wake_r)
        if wake_w is not None:
            os.close(wake_w)
        os.close(tty_fd)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
