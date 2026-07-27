import subprocess


def run_commands():
    subprocess.run(["echo", "real"])
    subprocess.run(
        ["echo", "second"],
        check=True,
    )
    text = 'subprocess.run(["fake"])'
    # subprocess.run(["comment"])
    return text
