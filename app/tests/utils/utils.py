import random
import string


def random_lower_string(length: int = 12) -> str:
    """Generate a random string of lowercase letters."""
    return "".join(random.choice(string.ascii_lowercase) for _ in range(length))


def random_email() -> str:
    """Generate a random email address."""
    return f"{random_lower_string()}@example.com"
