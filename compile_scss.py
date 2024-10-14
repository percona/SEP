import sass
import os

def compile_scss(input_file, output_file):
    """
    Compile SCSS file into CSS and write it to the specified output file.
    """
    try:
        compiled_css = sass.compile(filename=input_file)
        cleaned_css = compiled_css.replace(' }', '\n}')
        with open(output_file, 'w') as f:
            f.write(cleaned_css)
        print(f"Compiled {input_file} -> {output_file}")
    except Exception as e:
        print(f"Error compiling {input_file}: {e}")
        
def compile_all_scss_in_dir(input_dir, output_dir):
    """
    Compile all SCSS files in the input directory and its subdirectories,
    saving the corresponding CSS files in the output directory.
    """
    for root, _, files in os.walk(input_dir):
        for file in files:
            if file.endswith(".scss"):
                scss_file = os.path.join(root, file)
                
                # Create the corresponding CSS file path by replacing input_dir with output_dir
                relative_path = os.path.relpath(scss_file, input_dir)
                css_file = os.path.join(output_dir, relative_path).replace(".scss", ".css")
                
                # Ensure the output directory exists
                css_dir = os.path.dirname(css_file)
                if not os.path.exists(css_dir):
                    os.makedirs(css_dir)
                
                # Compile the SCSS file to CSS
                compile_scss(scss_file, css_file)

if __name__ == "__main__":
    # Define the input SCSS file and the output CSS file
    scss_dir = "static/scss"
    css_dir = "static/css"
    base_scss = os.path.join(scss_dir, "layout.scss")
    base_css = os.path.join(css_dir, "layout.css")
    
    # Create the output directory if it doesn't exist
    if not os.path.exists(css_dir):
        os.makedirs(css_dir)

    # Compile the SCSS file to CSS
    compile_scss(base_scss, base_css)
    
     # Compile all SCSS files in the input directory
    compile_all_scss_in_dir(os.path.join(scss_dir, "pages"), os.path.join(css_dir, "pages"))
