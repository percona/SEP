import sass
import os

def compile_scss(input_file, output_file):
    """
    Compile SCSS file into CSS and write it to the specified output file.
    """
    try:
        compiled_css = sass.compile(filename=input_file)
        with open(output_file, 'w') as f:
            f.write(compiled_css)
        print(f"Compiled {input_file} -> {output_file}")
    except Exception as e:
        print(f"Error compiling {input_file}: {e}")

if __name__ == "__main__":
    # Define the input SCSS file and the output CSS file
    scss_dir = "static/scss"
    css_dir = "static/css"
    input_scss = os.path.join(scss_dir, "style.scss")
    output_css = os.path.join(css_dir, "style.css")
    
    # Create the output directory if it doesn't exist
    if not os.path.exists(css_dir):
        os.makedirs(css_dir)

    # Compile the SCSS file to CSS
    compile_scss(input_scss, output_css)
