# nginx Log Colorizer

A fast, customizable Python script that colorizes nginx access logs with column-aligned output for easy visual scanning.

## Features

- **Column-aligned output** for vertical scanning of timestamps, hostnames, IPs, and status codes
- **Color-coded HTTP status codes**
  - 200: Bright green
  - 301/302: Blue
  - 304: Medium green
  - 403: Dark red
  - 404: Black-on-gray
  - 5xx: Black-on-red background
- **Color-coded cache status** (HIT/MISS/BYPASS)
- **IP address highlighting**
  - Your IP: Bright yellow (`--my-ip`)
  - Author IPs: Dark green (`--author-ip`)
  - Special servers: Orange (configurable)
- **Path highlighting**
  - Images: Dark purple
  - Custom patterns: Dark orange (configurable)
- **IPv4/IPv6 filtering**
- **Configurable output** (suppress referer/user-agent)

## Installation

1. Download `colorize-nginx-logs.py`
2. Make it executable:
   ```bash
   chmod +x colorize-nginx-logs.py
   ```
3. Optionally move to your PATH:
   ```bash
   sudo mv colorize-nginx-logs.py /usr/local/bin/colorize-nginx-logs
   ```

## Usage

```bash
# Tail live logs
tail -f /var/log/nginx/access.log | ./colorize-nginx-logs.py

# Process existing logs
cat /var/log/nginx/access.log | ./colorize-nginx-logs.py

# Show only IPv6 requests, suppress referer/UA
tail -f /var/log/nginx/access.log | ./colorize-nginx-logs.py -6 -shortshort

# Highlight your IP and author IPs
tail -f /var/log/nginx/access.log | ./colorize-nginx-logs.py -m 1.2.3.4 -a 5.6.7.8
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

## Required nginx Log Format

This script expects the following custom nginx log format:

```nginx
log_format custom '[$time_local] $server_name | $remote_addr | $status [$upstream_cache_status] ${scheme_if_http}$request | Ref: "$http_referer" UA: "$http_user_agent"';
```

Add this to your `nginx.conf` and use it in your access log declaration:

```nginx
access_log /var/log/nginx/access.log custom;
```

**Note:** For the `${scheme_if_http}` variable, add this to your `http` block:

```nginx
map $scheme $scheme_if_http {
    http "http://";
    default "";
}
```

## Requirements

- Python 3.6+
- No external dependencies (uses only standard library)

## Performance

The script is optimized for real-time log streaming:
- Compiled regex patterns for fast parsing
- Lookup tables for color codes
- Line buffering for immediate output
- Efficient string formatting

## License

This software is released into the public domain under the [Unlicense](http://unlicense.org/).

Do whatever you want with it!
