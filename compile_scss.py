"""The module provides functions to compile SCSS files into CSS.

It can compile individual SCSS files or all SCSS files in a directory and its subdirectories.
"""

import logging
import os
from pathlib import Path

import sass

# Set up logging
logging.basicConfig(level=logging.INFO)


def compile_scss(input_file: Path, output_file: Path) -> None:
    """Compile SCSS file into CSS and write it to the specified output file."""
    try:
        compiled_css = sass.compile(filename=str(input_file))
        cleaned_css = compiled_css.replace(" }", "\n}")
        with output_file.open("w") as f:
            f.write(cleaned_css)
        logging.info("Compiled %s -> %s", input_file, output_file)
    except (sass.CompileError, OSError):
        logging.exception("Error compiling %s", input_file)


def compile_all_scss_in_dir(input_dir: Path, output_dir: Path) -> None:
    """Compile all SCSS files in the input directory and its subdirectories.

    Save the corresponding CSS files in the output directory.
    """
    for root, _, files in os.walk(input_dir):
        for file in files:
            if file.endswith(".scss"):
                scss_file = Path(root) / file

                # Create the corresponding CSS file path by replacing input_dir with output_dir
                relative_path = scss_file.relative_to(input_dir)
                css_file = (output_dir / relative_path).with_suffix(".css")

                # Ensure the output directory exists
                css_dir = css_file.parent
                if not css_dir.exists():
                    css_dir.mkdir(parents=True)

                # Compile the SCSS file to CSS
                compile_scss(scss_file, css_file)


if __name__ == "__main__":
    # Define the input SCSS file and the output CSS file
    scss_dir = Path("static/scss")
    css_dir = Path("static/css")
    base_scss = scss_dir / "layout.scss"
    base_css = css_dir / "layout.css"

    # Create the output directory if it doesn't exist
    if not css_dir.exists():
        css_dir.mkdir(parents=True)

    # Compile the SCSS file to CSS
    compile_scss(base_scss, base_css)

    # Compile all SCSS files in the input directory
    compile_all_scss_in_dir(scss_dir / "pages", css_dir / "pages")
