import urllib.error
import urllib.request
from wsgiref.handlers import format_date_time
from datetime import datetime, timedelta
import email.utils as eutils

def parse_http_date(httpdate):
    return datetime(*eutils.parsedate(httpdate)[:6])

def http_request(url, user_agent=None, accept=None, last_modified=None, headers=dict()):
    use_headers = {}
    if user_agent is not None:
        use_headers["User-Agent"] = user_agent
    if accept is not None:
        use_headers["Accept"] = accept
    use_headers.update(headers)
    if last_modified is not None:
        headers["If-Modified-Since"] = format_date_time(to_timestamp(last_modified))

    request = urllib.request.Request(url, headers=headers)
    response = urllib.request.urlopen(request, timeout=3)
    last_modified = response.info().get("Last-Modified", None)
    if last_modified is not None:
        timestamp = parse_http_date(last_modified)
    else:
        timestamp = None
    return response, timestamp

def date_to_key(date):
    return (date.year, date.month, date.day, date.hour)
