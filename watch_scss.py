import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from compile_scss import compile_scss
import os

class SCSSWatchHandler(FileSystemEventHandler):
    def __init__(self, scss_file, css_file):
        self.scss_file = scss_file
        self.css_file = css_file

    def on_modified(self, event):
        if event.src_path.endswith(".scss"):
            print(f"Detected change in {event.src_path}. Recompiling SCSS...")
            compile_scss(self.scss_file, self.css_file)

if __name__ == "__main__":
    scss_dir = "static/scss"
    css_dir = "static/css"
    input_scss = os.path.join(scss_dir, "style.scss")
    output_css = os.path.join(css_dir, "style.css")

    # Set up observer to watch SCSS files
    event_handler = SCSSWatchHandler(input_scss, output_css)
    observer = Observer()
    observer.schedule(event_handler, scss_dir, recursive=True)

    print(f"Watching SCSS files in {scss_dir}...")
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()
