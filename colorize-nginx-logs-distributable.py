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
Colorize nginx logs with automatic format detection (v4.0).

Supports both nginx "combined" format (default) and custom formats with cache status.

Usage: tail -f /var/log/nginx/access.log | ./colorize-nginx-logs.py [options]
       cat /var/log/nginx/access.log | ./colorize-nginx-logs.py [options]

Options:
  -short       Suppress referrer output (show only UA)
  -shortshort  Suppress both referrer and user agent output
  -4           Display only IPv4 requests
  -6           Display only IPv6 requests
  --my-ip, -m  Highlight your IP address in bright yellow
  --author-ip, -a  Highlight post author IP (can be used multiple times, max 4)

Features:
  - Auto-detects nginx log format (combined or custom)
  - Column-aligned output for vertical scanning
  - Color-coded HTTP status (200=green, 301/302=blue, 304=green, 403=red, 404=gray, 5xx=red bg)
  - Color-coded cache status when available ([H]=green, [M]=blue, [B]=yellow, [-]=gray)
  - IP highlighting: your IP (bright yellow), post authors (bright green), special servers (orange)
  - Path highlighting: custom patterns (dark orange), images (dark purple)
"""

import sys
import re
import argparse

# ============================================================================
# USER CONFIGURATION
# ============================================================================
# Customize these values for your environment

# Special server IPs to highlight in orange (e.g., internal servers, app servers)
# Add IP addresses that you want to stand out in the logs
SPECIAL_SERVER_IPS = [
    # '172.31.20.227',  # Example: Internal app server
    # '10.0.1.50',      # Example: Database server
]

# Path patterns to highlight in dark orange
# Add strings that, when found in request paths, should be highlighted
SPECIAL_PATH_PATTERNS = [
    # 'wp-discourse',   # Example: WordPress plugin paths
    # 'api/v2',         # Example: API endpoints
    # '/admin',         # Example: Admin paths
]

# Maximum hostname width for column alignment
# Set this to the length of your longest hostname for proper alignment
# Example: if your longest hostname is "www.example.com" (15 chars), set to 15
HOSTNAME_WIDTH = 24

# ============================================================================
# END USER CONFIGURATION
# ============================================================================

# Column widths for alignment
TIMESTAMP_WIDTH = 29  # [23/Dec/2025:11:17:05 -0600]
IP_WIDTH_IPV4 = 15    # xxx.xxx.xxx.xxx
IP_WIDTH_IPV6 = 40    # Full IPv6 address
METHOD_WIDTH = 6      # GET, POST, DELETE, etc.
STATUS_WIDTH = 3      # 200, 404, etc.
CACHE_WIDTH = 3       # [B], [H], [M], [-]

# Compiled regex patterns for log parsing (performance optimization)
# Standard nginx "combined" format: $remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent"
COMBINED_PATTERN = re.compile(r'^(\S+) - (\S+) \[([^\]]+)\] "([^"]*)" (\d+) (\S+) "([^"]*)" "([^"]*)"')

# Custom format with cache status and server name (backward compatibility)
CUSTOM_PATTERN = re.compile(r'^\[([^\]]+)\] ([^\|]+) \| ([^\|]+) \| (\d+) \[([^\]]+)\] (.*?) \| Ref: "(.*?)" UA: "(.*?)"\s*$')

# Image file extensions for path colorization
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico')

# ANSI color codes
class Colors:
    RESET = '\033[0m'

    # Text colors
    DARK_GRAY = '\033[90m'             # Timestamp, Ref, UA
    CYAN = '\033[36m'                  # IP address
    ORANGE = '\033[38;5;208m'          # Special server IPs
    DARK_ORANGE = '\033[38;5;94m'      # Special path patterns
    BRIGHT_CYAN = '\033[96m'           # Server name
    MAGENTA = '\033[35m'               # Pipe separators
    DARK_PURPLE = '\033[38;5;90m'      # Image requests (dark magenta)
    RED = '\033[31m'                   # POST method
    GRAY = '\033[90m'                  # HEAD/other methods
    BRIGHT_YELLOW = '\033[93m'         # User's own IP
    DARK_GREEN = '\033[38;5;028m'      # Post author IPs

    # HTTP status code colors
    STATUS_200 = '\033[92m'            # Bright green for 200 OK
    STATUS_REDIRECT = '\033[38;5;039m' # Fun blue for 301, 302
    STATUS_304 = '\033[38;5;028m'      # Medium-bright green for 304 Not Modified
    STATUS_403 = '\033[38;5;124m'      # Dark red for 403 Forbidden
    STATUS_404 = '\033[30;47m'         # Black-on-gray for 404 Not Found
    STATUS_5XX = '\033[30;101m'        # Black-on-red 5xx Server Errors
    STATUS_OTHER = '\033[1;37m'        # Bold white for all else

    # Cache status colors
    CACHE_HIT = '\033[32m'             # Green for HIT
    CACHE_BYPASS = '\033[33m'          # Yellow for BYPASS
    CACHE_MISS = '\033[34m'            # Blue for MISS
    CACHE_NONE = '\033[90m'            # Gray for - (no cache status provided)

# Fast lookup tables for status/cache colors
STATUS_COLOR_MAP = {
    '200': Colors.STATUS_200,
    '301': Colors.STATUS_REDIRECT,
    '302': Colors.STATUS_REDIRECT,
    '304': Colors.STATUS_304,
    '400': Colors.STATUS_403,
    '403': Colors.STATUS_403,
    '404': Colors.STATUS_404,
    '405': Colors.STATUS_403,
}

CACHE_COLOR_MAP = {
    'HIT': Colors.CACHE_HIT,
    'BYPASS': Colors.CACHE_BYPASS,
    'MISS': Colors.CACHE_MISS,
}

CACHE_ABBREV_MAP = {
    'HIT': 'H',
    'BYPASS': 'B',
    'MISS': 'M',
    '-': '-',
}

def is_ipv6(ip_addr):
    """Check if an IP address is IPv6 (contains colons)."""
    return ':' in ip_addr

def is_ipv4(ip_addr):
    """Check if an IP address is IPv4 (contains dots)."""
    return '.' in ip_addr

def get_cache_color(status):
    """Return color based on cache status."""
    status = status.strip()
    return CACHE_COLOR_MAP.get(status, Colors.CACHE_NONE)

def get_cache_abbrev(status):
    """Return abbreviated cache status."""
    status = status.strip()
    return CACHE_ABBREV_MAP.get(status, '---')

def get_status_color(status_code):
    """Return color based on HTTP status code."""
    # Check for 5xx server errors
    if status_code.startswith('5'):
        return Colors.STATUS_5XX
    return STATUS_COLOR_MAP.get(status_code, Colors.STATUS_OTHER)

def parse_request(request):
    """Parse HTTP request into method and remaining components."""
    request = request.strip()

    # Remove scheme prefix if present (from ${scheme_if_http})
    scheme = ''
    rest = request
    if request.startswith('http://') or request.startswith('https://'):
        scheme_end = request.find('://')
        scheme = request[:scheme_end+3]
        rest = request[scheme_end+3:]

    # Parse method, path, version
    parts = rest.split(None, 2)  # Split on whitespace, max 3 parts
    if len(parts) != 3:
        # Malformed request, return None for method and full request as path
        return None, request

    method, path, version = parts
    return method, (scheme, path, version)

def colorize_method(method):
    """Colorize HTTP method."""
    if method is None:
        return ''

    # Determine method color
    if method == 'POST':
        method_color = Colors.RED
    elif method in ('HEAD', 'OPTIONS', 'TRACE', 'CONNECT'):
        method_color = Colors.GRAY
    else:
        method_color = Colors.RESET  # Default color for GET, etc.

    return f"{method_color}{method}{Colors.RESET}"

def colorize_path(path_info):
    """Colorize path and version."""
    if isinstance(path_info, str):
        # Malformed request, return as-is
        return path_info

    scheme, path, version = path_info

    # Determine path color based on configured patterns
    path_color = Colors.RESET  # Default color

    # Check for special path patterns
    for pattern in SPECIAL_PATH_PATTERNS:
        if pattern in path:
            path_color = Colors.DARK_ORANGE
            break

    # Check for image extensions (takes precedence over special patterns)
    if path.lower().endswith(IMAGE_EXTENSIONS):
        path_color = Colors.DARK_PURPLE

    # Build colorized path
    colorized = f"{scheme}{path_color}{path}{Colors.RESET}"

    # Only append version if it's not HTTP/2.0 (the common case)
    if version != "HTTP/2.0":
        colorized += f" {version}"

    return colorized

def detect_format(line):
    """Detect which log format is being used. Returns ('combined', match) or ('custom', match) or (None, None)."""
    # Try custom format first (more specific)
    match = CUSTOM_PATTERN.match(line)
    if match:
        return 'custom', match

    # Try combined format
    match = COMBINED_PATTERN.match(line)
    if match:
        return 'combined', match

    return None, None

def colorize_log_line(line, show_referer=True, show_ua=True, ip_width=IP_WIDTH_IPV4, pre_match=None, pre_format=None, my_ip=None, author_ips=None):
    """Colorize a single nginx log line (supports both combined and custom formats)."""

    # Detect format if not already done
    if pre_match is not None and pre_format is not None:
        log_format = pre_format
        match = pre_match
    else:
        log_format, match = detect_format(line)

    if not match:
        # If line doesn't match any format, return it as-is
        return line

    # Parse based on format
    if log_format == 'combined':
        # combined format: $remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent"
        remote_addr, remote_user, timestamp, request, status, body_bytes_sent, referer, user_agent = match.groups()
        server_name = None
        cache_status = None
    else:  # custom format
        # custom format: [$time_local] $server_name | $remote_addr | $status [$upstream_cache_status] ${scheme_if_http}$request | Ref: "$http_referer" UA: "$http_user_agent"
        timestamp, server_name, remote_addr, status, cache_status, request, referer, user_agent = match.groups()
        cache_status = cache_status.strip() if cache_status else None

    # Right-align fields for column alignment
    timestamp_formatted = f"[{timestamp}]".ljust(TIMESTAMP_WIDTH)  # Left-align timestamp (it's consistent)

    # Format IP address - left-aligned
    ip_addr = remote_addr.strip()
    ip_formatted = ip_addr.ljust(ip_width)

    # Determine IP color with priority: my_ip > author_ips > special servers > default
    if my_ip and ip_addr == my_ip:
        ip_color = Colors.BRIGHT_YELLOW
    elif author_ips and ip_addr in author_ips:
        ip_color = Colors.DARK_GREEN
    elif ip_addr in SPECIAL_SERVER_IPS:
        ip_color = Colors.ORANGE
    else:
        ip_color = Colors.BRIGHT_CYAN

    # Parse request into method and path components
    method, path_info = parse_request(request)

    status_formatted = status.rjust(STATUS_WIDTH)

    # Build base colorized line with aligned columns
    colorized = (
        f"{Colors.DARK_GRAY}{timestamp_formatted}{Colors.RESET} "
    )

    # Add server name if available (custom format only)
    if server_name:
        hostname_formatted = server_name.strip().rjust(HOSTNAME_WIDTH)
        colorized += f"{Colors.CYAN}{hostname_formatted}{Colors.RESET}  "

    colorized += (
        f"{ip_color}{ip_formatted}{Colors.RESET} "
        f"{colorize_method(method).ljust(METHOD_WIDTH)} "
        f"{get_status_color(status)}{status_formatted}{Colors.RESET} "
    )

    # Add cache status if available (custom format only)
    if cache_status is not None:
        cache_formatted = f"[{get_cache_abbrev(cache_status)}]"
        colorized += f"{get_cache_color(cache_status)}{cache_formatted}{Colors.RESET} "

    colorized += f"{colorize_path(path_info)}"

    # Add optional fields based on flags
    if show_referer and show_ua:
        colorized += f" {Colors.DARK_GRAY}Ref: \"{referer}\" UA: \"{user_agent}\"{Colors.RESET}"
    elif show_referer:
        colorized += f" {Colors.DARK_GRAY}Ref: \"{referer}\"{Colors.RESET}"
    elif show_ua:
        colorized += f" {Colors.DARK_GRAY}UA: \"{user_agent}\"{Colors.RESET}"

    return colorized

def main():
    """Read from stdin and colorize each line."""
    parser = argparse.ArgumentParser(
        description='Colorize nginx logs with column alignment',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  tail -f /var/log/nginx/access.log | %(prog)s
  tail -f /var/log/nginx/access.log | %(prog)s -short
  tail -f /var/log/nginx/access.log | %(prog)s -shortshort
  tail -f /var/log/nginx/access.log | %(prog)s -4
  tail -f /var/log/nginx/access.log | %(prog)s -6
  tail -f /var/log/nginx/access.log | %(prog)s -6 -shortshort
  tail -f /var/log/nginx/access.log | %(prog)s -m 1.2.3.4
  tail -f /var/log/nginx/access.log | %(prog)s -m 1.2.3.4 -a 5.6.7.8 -a 9.10.11.12
        """
    )
    parser.add_argument('-short', action='store_true',
                       help='Suppress referrer output')
    parser.add_argument('-shortshort', action='store_true',
                       help='Suppress both referrer and user agent output')
    parser.add_argument('-4', dest='ipv4_only', action='store_true',
                       help='Display only IPv4 requests')
    parser.add_argument('-6', dest='ipv6_only', action='store_true',
                       help='Display only IPv6 requests')
    parser.add_argument('--my-ip', '-m', dest='my_ip',
                       help='Highlight your IP address in bright yellow')
    parser.add_argument('--author-ip', '-a', dest='author_ips', action='append',
                       help='Highlight post author IP in bright green (can be used multiple times, max 4)')

    args = parser.parse_args()

    # Validate author IPs count
    if args.author_ips and len(args.author_ips) > 4:
        parser.error('Maximum 4 author IPs allowed')

    # Convert author_ips to a set for faster lookup, or None if not provided
    author_ips_set = set(args.author_ips) if args.author_ips else None

    # Determine what to show based on flags
    show_referer = not args.short and not args.shortshort
    show_ua = not args.shortshort

    # Determine IP width based on IPv6 filter
    ip_width = IP_WIDTH_IPV6 if args.ipv6_only else IP_WIDTH_IPV4

    try:
        try:
            sys.stdout.reconfigure(line_buffering=True)
        except AttributeError:
            pass
        ipv4_only = args.ipv4_only
        ipv6_only = args.ipv6_only
        detect = detect_format
        colorize = colorize_log_line
        write = sys.stdout.write
        for line in sys.stdin:
            # Remove trailing newline
            line = line.rstrip('\n')

            # Filter by IP version if requested
            if ipv4_only or ipv6_only:
                # Extract IP address from log line to filter
                log_format, match = detect(line)
                if match:
                    # Get IP address based on format (different group positions)
                    if log_format == 'combined':
                        ip_addr = match.group(1).strip()  # remote_addr is group 1 in combined
                    else:  # custom
                        ip_addr = match.group(3).strip()  # remote_addr is group 3 in custom

                    # Skip this line if it doesn't match the filter
                    if ipv4_only and not is_ipv4(ip_addr):
                        continue
                    if ipv6_only and not is_ipv6(ip_addr):
                        continue
                else:
                    write(line + "\n")
                    continue

            # Colorize and print
            colorized = colorize(line, show_referer=show_referer, show_ua=show_ua, ip_width=ip_width,
                               pre_match=match if (ipv4_only or ipv6_only) else None,
                               pre_format=log_format if (ipv4_only or ipv6_only) else None,
                               my_ip=args.my_ip, author_ips=author_ips_set)
            write(colorized + "\n")
    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully
        pass
    except BrokenPipeError:
        # Handle pipe being closed
        pass

if __name__ == '__main__':
    main()
