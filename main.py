from query import load_servers
from tray import TrayApp


def main():
    TrayApp(load_servers()).run()


if __name__ == "__main__":
    main()
