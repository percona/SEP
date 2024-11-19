"""Define utilities shared across the task executors."""

from python_minifier import minify


def minify_file_content(content: str, file_ext: str = "") -> str:
    """Minify Python file content.

    Minify the given Python code string if the file extension is ".py" or not
    specified. For other file types, return the content unchanged.

    :param content: The content to be minified.
    :type content: str
    :param file_ext: The file extension indicating the type of content.
    :type file_ext: str, optional
    :return: The minified content if applicable, otherwise the original content.
    :rtype: str
    """
    file_ext = file_ext.lstrip(".").lower()
    if file_ext and file_ext != "py":
        return content
    try:
        return minify(
            content,
            remove_annotations=True,
            remove_pass=True,
            remove_literal_statements=True,
            combine_imports=True,
            hoist_literals=True,
            rename_locals=True,
            rename_globals=True,
            remove_object_base=True,
            remove_asserts=True,
            remove_debug=True,
            remove_explicit_return_none=True,
            remove_builtin_exception_brackets=True,
        )
    except SyntaxError:
        return content
