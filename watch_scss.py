import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from compile_scss import compile_scss, compile_all_scss_in_dir
import os

class SCSSWatchHandler(FileSystemEventHandler):
    def __init__(self, scss_file, css_file, pages_scss_dir, pages_css_dir):
        self.scss_file = scss_file
        self.css_file = css_file
        self.pages_scss_dir = pages_scss_dir
        self.pages_css_dir = pages_css_dir

    def on_modified(self, event):
        if event.src_path.endswith(".scss"):
            print(f"Detected change in {event.src_path}. Recompiling SCSS...")
            
            # Check if the change is in the pages directory
            if self.pages_scss_dir in event.src_path:
                print(f"Change detected in pages directory. Compiling all SCSS files in {self.pages_scss_dir}...")
                compile_all_scss_in_dir(self.pages_scss_dir, self.pages_css_dir)
            else:
                print(f"Detected change in {event.src_path}. Recompiling SCSS...")
                compile_scss(self.scss_file, self.css_file)


if __name__ == "__main__":
    scss_dir = "static/scss"
    css_dir = "static/css"
    pages_scss_dir = "pages/scss"
    pages_css_dir = "pages/css"

    # Set up observer to watch SCSS files in both directories
    event_handler = SCSSWatchHandler(
        os.path.join(scss_dir, "layout.scss"),
        os.path.join(css_dir, "layout.css"),
        pages_scss_dir,
        pages_css_dir
    )
    observer = Observer()

    # Watch both static/scss and pages/scss directories
    observer.schedule(event_handler, scss_dir, recursive=True)
    observer.schedule(event_handler, pages_scss_dir, recursive=True)

    print(f"Watching SCSS files in {scss_dir} and {pages_scss_dir}...")
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()
