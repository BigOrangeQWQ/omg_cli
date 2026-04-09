import random
import string


def random_string(length: int) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=length))


def snake_to_pascal(snake_str: str) -> str:
    components = snake_str.split("_")
    return "".join(x.title() for x in components)
