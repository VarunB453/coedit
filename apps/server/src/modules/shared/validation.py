import re

MAX_NAME_LENGTH = 100


def validate_name(value):
	if not isinstance(value, str):
		return None
	name = value.strip()
	device_name = re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", name, re.IGNORECASE)
	if (
		not name
		or len(name) > MAX_NAME_LENGTH
		or name in {".", ".."}
		or device_name
		or name.endswith(".")
		or re.search(r'[<>:"|?*/\\\x00-\x1f]', name)
		or any(ord(char) < 32 for char in name)
	):
		return None
	return name
