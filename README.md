# nginx Log Colorizer

A fast, customizable Python toolkit for viewing nginx access logs with color-coded output and no line wrapping.

**Two tools included:**
1. **colorize-nginx-logs.py** - Colorizes and formats nginx logs (works out-of-the-box with nginx's default "combined" format!)
2. **lognowrap.py** - Displays long lines without wrapping (horizontal scrolling with arrow keys)

## Features

### colorize-nginx-logs.py
- **Auto-detects log format** - Works with nginx "combined" format (default) and custom formats
- **Column-aligned output** for vertical scanning of timestamps, IPs, and status codes
- **Color-coded HTTP status codes** (256-color for better terminal compatibility)
  - 200: Bright green
  - 301/302: Blue
  - 304: Medium green
  - 403: Dark red
  - 404: Dark gray on light gray
  - 5xx: Black on bright red background
- **Color-coded cache status** (when using custom format with cache headers)
- **IP address highlighting**
  - Your IP: Bright yellow (`--my-ip`)
  - Author IPs: Dark green (`--author-ip`)
  - Special servers: Orange (configurable)
- **Path highlighting**
  - Images: Dark purple
  - Custom patterns: Dark orange (configurable)
- **IPv4/IPv6 filtering**
- **Configurable output** (suppress referer/user-agent)

### lognowrap.py
- **No line wrapping** - Long lines scroll horizontally instead of wrapping
- **Arrow key navigation** - Use left/right arrows to scroll through long lines
- **Preserves ANSI codes** - All colors and formatting pass through unchanged
- **Real-time streaming** - Displays logs as they arrive with no buffering
- **Terminal resize handling** - Automatically adjusts viewport on window resize
- **Universal tool** - Works with any ANSI-colored input, not just nginx logs

## Installation

1. Download both scripts:
   - `colorize-nginx-logs-distributable.py`
   - `lognowrap.py`
2. Make them executable:
   ```bash
   chmod +x colorize-nginx-logs-distributable.py lognowrap.py
   ```
3. Optionally move to your PATH:
   ```bash
   sudo mv colorize-nginx-logs-distributable.py /usr/local/bin/colorize-nginx-logs
   sudo mv lognowrap.py /usr/local/bin/lognowrap
   ```
4. (Optional) Install wcwidth for better Unicode support in lognowrap:
   ```bash
   pip3 install wcwidth
   ```

## Usage

### Basic Usage (colorizer only)

```bash
# Tail live logs
tail -f /var/log/nginx/access.log | ./colorize-nginx-logs-distributable.py

# Process existing logs
cat /var/log/nginx/access.log | ./colorize-nginx-logs-distributable.py

# Show only IPv6 requests, suppress referer/UA
tail -f /var/log/nginx/access.log | ./colorize-nginx-logs-distributable.py -6 -shortshort

# Highlight your IP and author IPs
tail -f /var/log/nginx/access.log | ./colorize-nginx-logs-distributable.py -m 1.2.3.4 -a 5.6.7.8
```

### With lognowrap (recommended for long lines)

```bash
# Tail live logs without line wrapping
tail -f /var/log/nginx/access.log | ./colorize-nginx-logs-distributable.py | ./lognowrap.py

# View logs with horizontal scrolling (use arrow keys)
cat /var/log/nginx/access.log | ./colorize-nginx-logs-distributable.py | ./lognowrap.py

# Combine with filters
tail -f /var/log/nginx/access.log | ./colorize-nginx-logs-distributable.py -6 -shortshort | ./lognowrap.py

# If installed to PATH
tail -f /var/log/nginx/access.log | colorize-nginx-logs | lognowrap
```

**lognowrap controls:**
- `Left Arrow` - Scroll left
- `Right Arrow` - Scroll right
- `Ctrl+C` - Exit
```

## Options

```
-short              Suppress referrer output (show only UA)
-shortshort         Suppress both referrer and user agent
-4                  Display only IPv4 requests
-6                  Display only IPv6 requests
--my-ip, -m IP      Highlight your IP in bright yellow
--author-ip, -a IP  Highlight author IPs in dark green (up to 4)
```

## Configuration

Edit the configuration section at the top of the script:

```python
# Special server IPs to highlight in orange
SPECIAL_SERVER_IPS = [
    '172.31.20.227',  # Internal app server
    '10.0.1.50',      # Database server
]

# Path patterns to highlight in dark orange
SPECIAL_PATH_PATTERNS = [
    'wp-discourse',   # WordPress plugin paths
    'api/v2',         # API endpoints
    '/admin',         # Admin paths
]

# Maximum hostname width for column alignment
HOSTNAME_WIDTH = 24  # Adjust to your longest hostname
```

## Log Format Support

### Default Format (No Configuration Required)

The script works out-of-the-box with nginx's standard **combined** log format:

```nginx
log_format combined '$remote_addr - $remote_user [$time_local] '
                    '"$request" $status $body_bytes_sent '
                    '"$http_referer" "$http_user_agent"';
```

This is nginx's default format, so you can start using the colorizer immediately!

### Optional: Custom Format with Cache Status

For advanced features like cache status display and server name column, you can use this custom format:

```nginx
log_format show_hosts '[$time_local] $server_name | $remote_addr | $status [$upstream_cache_status] ${scheme_if_http}$request | Ref: "$http_referer" UA: "$http_user_agent"';
```

> **Note:** This colorizer was originally designed to work with this custom `show_hosts` format, which provides additional visibility into cache performance and virtual host routing. Support for the standard "combined" format was added later to make the tool more accessible.

Then enable it in your access log:

```nginx
access_log /var/log/nginx/access.log show_hosts;
```

**Note:** For the `${scheme_if_http}` variable, add this to your `http` block:

```nginx
map $scheme $scheme_if_http {
    http "http://";
    default "";
}
```

The script automatically detects which format is being used.

## Requirements

### colorize-nginx-logs-distributable.py
- Python 3.6+
- No external dependencies (uses only standard library)

### lognowrap.py
- Python 3.6+
- Standard library only (required)
- `wcwidth` library (optional, for better Unicode width detection)

## Performance

### colorize-nginx-logs-distributable.py
The colorizer is optimized for real-time log streaming:
- Compiled regex patterns for fast parsing
- Lookup tables for color codes
- Line buffering for immediate output
- Efficient string formatting

### lognowrap.py
The display wrapper is designed for high-volume streaming:
- Memory: O(terminal_height) - only stores visible screen lines
- CPU: Minimal when idle, responsive during streaming
- Latency: <100ms from input to display
- Non-blocking I/O for smooth real-time updates

## Why Two Tools?

**Separation of concerns:** The colorizer focuses on parsing and formatting nginx logs. The display wrapper handles terminal rendering and navigation. This design:
- Keeps each tool simple and maintainable
- Allows lognowrap to work with any ANSI-colored input, not just nginx logs
- Lets you use the colorizer standalone if you don't need horizontal scrolling
- Follows the Unix philosophy: each tool does one thing well

## License

This software is released into the public domain under the [Unlicense](http://unlicense.org/).

Do whatever you want with it!
