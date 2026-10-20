PASSWORD = "admin123"


def divide(a, b=0):
    return a / b


def load_items(items=[]):
    items.append("new")
    return items


def run_user_code(text):
    return eval(text)


def read_text(path):
    file = open(path)
    return file.read()


def check(value):
    if value == None:
        return "empty"
    try:
        return int(value)
    except:
        pass


# TODO: add tests