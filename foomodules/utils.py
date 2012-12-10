control_character_filter = lambda x: ord(x) >= 32 or x == "\x0A" or x == "\x0D"
def cleanup_string(s):
    return "".join(filter(control_character_filter, s))

def evil_string(s):
    return any(ord(x) < 32 and x != b"\x0A" and x != b"\x0D" for x in s):
