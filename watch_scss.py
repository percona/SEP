"""Module to watch SCSS files and recompile them when modified.

Uses watchdog to monitor file changes.
"""

import logging
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from compile_scss import compile_all_scss_in_dir, compile_scss

# Initialize logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


class SCSSWatchHandler(FileSystemEventHandler):
    """Handles changes in SCSS files by recompiling them."""

    def __init__(
        self, scss_file: Path, css_file: Path, pages_scss_dir: Path, pages_css_dir: Path
    ) -> None:
        """Initialize the SCSSWatchHandler with paths to the SCSS and CSS files, and directories.

        :param scss_file: Path to the main SCSS file
        :param css_file: Path to the output CSS file
        :param pages_scss_dir: Directory for SCSS files in the pages folder
        :param pages_css_dir: Directory for CSS files in the pages folder
        """
        self.scss_file = scss_file
        self.css_file = css_file
        self.pages_scss_dir = pages_scss_dir
        self.pages_css_dir = pages_css_dir

    def on_modified(self, event: FileSystemEvent) -> None:
        """Respond to modifications of SCSS files by recompiling the SCSS to CSS.

        :param event: The event object representing the file system change
        """
        if event.src_path.endswith(".scss"):
            logging.info("Detected change in %s. Recompiling SCSS...", event.src_path)

            # Check if the change is in the pages directory
            if str(self.pages_scss_dir) in event.src_path:
                logging.info(
                    "Change detected in pages directory. Compiling all SCSS files in %s...",
                    self.pages_scss_dir,
                )
                compile_all_scss_in_dir(self.pages_scss_dir, self.pages_css_dir)
            else:
                logging.info(
                    "Detected change in %s. Recompiling SCSS...", event.src_path
                )
                compile_scss(self.scss_file, self.css_file)


if __name__ == "__main__":
    scss_dir = Path("static/scss")
    css_dir = Path("static/css")
    pages_scss_dir = Path("pages/scss")
    pages_css_dir = Path("pages/css")

    # Set up observer to watch SCSS files in both directories
    event_handler = SCSSWatchHandler(
        scss_dir / "layout.scss", css_dir / "layout.css", pages_scss_dir, pages_css_dir
    )
    observer = Observer()

    # Watch both static/scss and pages/scss directories
    observer.schedule(event_handler, str(scss_dir), recursive=True)
    observer.schedule(event_handler, str(pages_scss_dir), recursive=True)

    logging.info("Watching SCSS files in %s and %s...", scss_dir, pages_scss_dir)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()
