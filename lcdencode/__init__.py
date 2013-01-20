import codecs

from . import HD44780A00

mapping = {
    "hd44780a00": HD44780A00.getregentry()
}

def search_function(encoding):
    return mapping.get(encoding, None)

codecs.register(search_function)
