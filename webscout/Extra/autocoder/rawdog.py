"""RawDog module for generating and auto-executing Python scripts in the CLI."""

import os
import re
import sys
import queue
import tempfile
import threading
import subprocess
from rich.panel import Panel
from rich.syntax import Syntax
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.table import Table
from rich.theme import Theme
from rich.live import Live
from rich.rule import Rule
from rich.box import ROUNDED
from typing import Optional, Generator, List, Tuple, Dict, Any
from webscout.AIutel import run_system_command
from .autocoder_utiles import get_intro_prompt

# Initialize LitLogger with custom format and colors 
default_path = tempfile.mkdtemp(prefix="webscout_autocoder")

# Custom theme for consistent styling
CUSTOM_THEME = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "red bold",
    "success": "green",
    "code": "blue",
    "output": "white",
})

console = Console(theme=CUSTOM_THEME)

class AutoCoder:
    """Generate and auto-execute Python scripts in the CLI with advanced error handling and retry logic.
    
    This class provides:
    - Automatic code generation 
    - Script execution with safety checks 
    - Advanced error handling and retries 
    - Beautiful logging with rich console
    - Execution result capture and display
    
    Examples:
        >>> coder = AutoCoder()
        >>> coder.execute("Get system info")
        Generating system info script...
        Script executed successfully!
    """

    def __init__(
        self,
        quiet: bool = False,
        internal_exec: bool = False,
        confirm_script: bool = False,
        interpreter: str = "python",
        prettify: bool = True,
        path_to_script: str = "",
        max_retries: int = 3,
        ai_instance = None
    ):
        """Initialize AutoCoder instance.

        Args:
            quiet (bool): Flag to control logging. Defaults to False.
            internal_exec (bool): Execute scripts with exec function. Defaults to False.
            confirm_script (bool): Give consent to scripts prior to execution. Defaults to False.
            interpreter (str): Python's interpreter name. Defaults to "python".
            prettify (bool): Prettify the code on stdout. Defaults to True.
            path_to_script (str): Path to save generated scripts. Defaults to "".
            max_retries (int): Maximum number of retry attempts. Defaults to 3.
            ai_instance: AI instance for error correction. Defaults to None.
        """
        self.internal_exec = internal_exec
        self.confirm_script = confirm_script
        self.quiet = quiet
        self.interpreter = interpreter
        self.prettify = prettify
        self.path_to_script = path_to_script or os.path.join(default_path, "execute_this.py")
        self.max_retries = max_retries
        self.tried_solutions = set()
        self.ai_instance = ai_instance
        self.last_execution_result = ""
        
        # Get Python version with enhanced logging
        if self.internal_exec:
            self.python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        else:
            version_output = run_system_command(
                f"{self.interpreter} --version",
                exit_on_error=True,
                stdout_error=True,
                help="If you're using Webscout-cli, use the flag '--internal-exec'"
            )[1].stdout
            self.python_version = version_output.split(" ")[1]



    def _extract_code_blocks(self, response: str) -> List[Tuple[str, str]]:
        """Extract code blocks from a response string.
        
        Args:
            response (str): Response string containing code blocks
            
        Returns:
            List[Tuple[str, str]]: List of (code_type, code) tuples
        """
        blocks = []
        
        # First try to find code blocks with explicit language tags
        pattern = r"```(\w+)\n(.*?)```"
        matches = re.finditer(pattern, response, re.DOTALL)
        
        for match in matches:
            code_type = match.group(1).lower()
            code = match.group(2).strip()
            blocks.append((code_type, code))
            
        # If no explicit code blocks found with language tags, try generic code blocks
        if not blocks:
            pattern = r"```(.*?)```"
            matches = re.finditer(pattern, response, re.DOTALL)
            for match in matches:
                code = match.group(1).strip()
                blocks.append(('python', code))
                
        # If still no code blocks found, treat as raw Python code
        if not blocks:
            lines = [line.strip() for line in response.split('\n') if line.strip()]
            if lines:
                blocks.append(('python', '\n'.join(lines)))
                    
        return blocks

    def _execute_code_block(self, code_type: str, code: str, ai_instance=None) -> Tuple[bool, str]:
        """Execute a code block.
        
        Args:
            code_type (str): Type of code block ('python')
            code (str): Code to execute
            ai_instance: Optional AI instance for error correction
            
        Returns:
            Tuple[bool, str]: (Success status, Error message or execution result)
        """
        try:
            result = self._execute_with_retry(code, ai_instance)
            if result is None:
                return True, self.last_execution_result
            return False, result
        except Exception as e:
            return False, str(e)

    def _format_output_panel(self, code: str, output_lines: list) -> Panel:
        """Format code and output into a single panel.
        
        Args:
            code (str): The code that was executed
            output_lines (list): List of output lines
            
        Returns:
            Panel: Formatted panel with code and output
        """
        # Format output
        output_text = "\n".join(output_lines) if output_lines else "Running..."
        
        # Create panel with Jupyter-like styling
        panel = Panel(
            output_text,
            title="[bold red]Out [1]:[/bold red]",
            border_style="red",
            expand=True,
            padding=(0, 1),
            box=ROUNDED
        )
            
        return panel

    def _format_result_panel(self, output: str) -> Panel:
        """Format execution result into a panel.
        
        Args:
            output (str): Execution output text
            
        Returns:
            Panel: Formatted panel with execution result
        """
        # Create panel with Jupyter-like styling
        panel = Panel(
            output,
            title="[bold red]Out [1]:[/bold red]",
            border_style="red",
            expand=True,
            padding=(0, 1),
            box=ROUNDED
        )
            
        return panel

    def _stream_output(self, process: subprocess.Popen) -> Generator[str, None, None]:
        """Stream output from a subprocess in realtime.
        
        Args:
            process: Subprocess to stream output from
            
        Yields:
            str: Lines of output
        """
        # Stream stdout
        output_lines = []
        for line in process.stdout:
            decoded_line = line.decode('utf-8').strip() if isinstance(line, bytes) else line.strip()
            if decoded_line:
                output_lines.append(decoded_line)
                yield decoded_line
                
        # Check stderr
        error = process.stderr.read() if process.stderr else None
        if error:
            error_str = error.decode('utf-8').strip() if isinstance(error, bytes) else error.strip()
            if error_str:
                yield f"Error: {error_str}"
                output_lines.append(f"Error: {error_str}")
        
        # Store the full execution result
        self.last_execution_result = "\n".join(output_lines)

    def _execute_with_retry(self, code: str, ai_instance=None) -> Optional[str]:
        """Execute code with retry logic and error correction.
        
        Args:
            code (str): Code to execute
            ai_instance: Optional AI instance for error correction

        Returns:
            Optional[str]: Error message if execution failed, None if successful
        """
        last_error = None
        retries = 0
        
        # Add the solution to tried solutions
        self.tried_solutions.add(code)
        
        # Print the code first
        if self.prettify:
            syntax = Syntax(code, "python", theme="monokai", line_numbers=True)
            console.print(Panel(
                syntax,
                title="[bold blue]In [1]:[/bold blue]",
                border_style="blue",
                expand=True,
                box=ROUNDED
            ))
        
        while retries < self.max_retries:
            try:
                if self.path_to_script:
                    script_dir = os.path.dirname(self.path_to_script)
                    if script_dir:
                        os.makedirs(script_dir, exist_ok=True)
                    with open(self.path_to_script, "w", encoding="utf-8") as f:
                        f.write(code)
                    
                if self.internal_exec:
                    # Create StringIO for output capture
                    import io
                    import sys
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    
                    # Create a queue for realtime output
                    output_queue = queue.Queue()
                    output_lines = []
                    
                    def execute_code():
                        try:
                            # Create a local namespace
                            local_namespace: Dict[str, Any] = {}
                            
                            # Redirect stdout/stderr
                            sys.stdout = stdout
                            sys.stderr = stderr
                            
                            # Execute the code
                            exec(code, globals(), local_namespace)
                            
                            # Get any output
                            output = stdout.getvalue()
                            error = stderr.getvalue()
                            
                            if error:
                                output_queue.put(("error", error))
                            if output:
                                output_queue.put(("output", output))
                                
                        except Exception as e:
                            output_queue.put(("error", str(e)))
                        finally:
                            # Restore stdout/stderr
                            sys.stdout = sys.__stdout__
                            sys.stderr = sys.__stderr__
                    
                    # Create and start execution thread
                    thread = threading.Thread(target=execute_code)
                    thread.daemon = True  # Make thread daemon to avoid hanging
                    thread.start()
                    
                    # Display output in realtime
                    with Live(auto_refresh=True) as live:
                        timeout_counter = 0
                        while thread.is_alive() or not output_queue.empty():
                            try:
                                msg_type, content = output_queue.get(timeout=0.1)
                                if content:
                                    new_lines = content.splitlines()
                                    output_lines.extend(new_lines)
                                    live.update(self._format_output_panel(code, output_lines))
                                    live.refresh()
                                output_queue.task_done()
                            except queue.Empty:
                                timeout_counter += 1
                                # Refresh the display to show it's still running
                                if timeout_counter % 10 == 0:  # Refresh every ~1 second
                                    live.update(self._format_output_panel(code, output_lines))
                                    live.refresh()
                                if timeout_counter > 100 and thread.is_alive():  # ~10 seconds
                                    output_lines.append("Warning: Execution taking longer than expected...")
                                    live.update(self._format_output_panel(code, output_lines))
                                    live.refresh()
                                continue
                    
                    # Wait for thread to complete with timeout
                    thread.join(timeout=30)  # 30 second timeout
                    if thread.is_alive():
                        output_lines.append("Error: Execution timed out after 30 seconds")
                        raise TimeoutError("Execution timed out after 30 seconds")
                    
                    # Check for any final errors
                    error = stderr.getvalue()
                    if error:
                        raise Exception(error)
                    
                    # Store the full execution result
                    self.last_execution_result = stdout.getvalue()
                    
                else:
                    try:
                        process = subprocess.Popen(
                            [self.interpreter, self.path_to_script],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,  # Use text mode to avoid encoding issues
                            bufsize=1,
                        )
                        
                        output_lines = []
                        # Stream output in realtime
                        with Live(auto_refresh=True) as live:
                            for line in self._stream_output(process):
                                output_lines.append(line)
                                live.update(self._format_output_panel(code, output_lines))
                                live.refresh()
                        
                        process.wait(timeout=30)  # 30 second timeout
                        
                        if process.returncode != 0:
                            # Try to read more detailed error information
                            if process.stderr:
                                error = process.stderr.read()
                                error_str = error.strip() if error else ""
                                if error_str:
                                    raise Exception(error_str)
                            raise Exception(f"Process exited with code {process.returncode}")
                        
                        # Store the full execution result
                        self.last_execution_result = "\n".join(output_lines)
                            
                    except subprocess.TimeoutExpired:
                        # Handle the case where the process times out
                        if process:
                            process.kill()
                        raise TimeoutError("Execution timed out after 30 seconds")
                
                return None
                
            except Exception as e:
                last_error = e
                if retries < self.max_retries - 1 and ai_instance:
                    error_context = self._get_error_context(e, code)
                    try:
                        # First try to fix the specific error
                        fixed_response = ai_instance.chat(error_context)
                        fixed_code = self._extract_code_from_response(fixed_response)
                        
                        if not fixed_code:
                            # If no code found, try a more general approach
                            general_context = f"""
The code failed with error: {str(e)}

Original Code:
```python
{code}
```

Please provide a complete, corrected version of the code that handles this error. The code should:
1. Handle any potential encoding issues
2. Include proper error handling
3. Use appropriate libraries and imports
4. Be compatible with the current Python environment

Provide only the corrected code without any explanation.
"""
                            fixed_response = ai_instance.chat(general_context)
                            fixed_code = self._extract_code_from_response(fixed_response)
                            
                            if not fixed_code:
                                break
                        
                        if self._is_similar_solution(fixed_code):
                            # If solution is too similar, try a different approach
                            different_context = f"""
Previous solutions were not successful. The code failed with error: {str(e)}

Original Code:
```python
{code}
```

Please provide a significantly different approach to solve this problem. Consider:
1. Using alternative libraries or methods
2. Implementing a different algorithm
3. Adding more robust error handling
4. Using a different encoding or data handling approach

Provide only the corrected code without any explanation.
"""
                            fixed_response = ai_instance.chat(different_context)
                            fixed_code = self._extract_code_from_response(fixed_response)
                            
                            if self._is_similar_solution(fixed_code):
                                break
                        
                        code = fixed_code
                        self.tried_solutions.add(code)
                        retries += 1
                        continue
                    except Exception as ai_error:
                        console.print(f"Error during AI correction: {str(ai_error)}", style="error")
                        break
                break
            
        return str(last_error) if last_error else "Unknown error occurred"

    def execute(self, prompt: str, ai_instance=None) -> bool:
        """Execute the given prompt using the appropriate executor.
        
        Args:
            prompt (str): Prompt to execute
            ai_instance: Optional AI instance for error correction
            
        Returns:
            bool: True if execution was successful, False otherwise
        """
        try:
            # Extract code blocks
            code_blocks = self._extract_code_blocks(prompt)
            if not code_blocks:
                console.print("No executable code found in the prompt", style="warning")
                return False

            # Execute each code block
            overall_success = True
            for code_type, code in code_blocks:
                success, result = self._execute_code_block(code_type, code, ai_instance)
                
                if not success:
                    console.print(f"Execution failed: {result}", style="error")
                    overall_success = False

            return overall_success
            
        except Exception as e:
            console.print(f"Error in execution: {str(e)}", style="error")
            return False

    def _extract_code_from_response(self, response: str) -> str:
        """Extract code from AI response.
        
        Args:
            response (str): AI response containing code blocks
            
        Returns:
            str: Extracted code from the first code block
        """
        code_blocks = self._extract_code_blocks(response)
        if not code_blocks:
            return ""
        
        # Return the content of the first code block, regardless of type
        return code_blocks[0][1]

    def _get_error_context(self, error: Exception, code: str) -> str:
        """Create context about the error for AI correction.
        
        Args:
            error (Exception): The caught exception
            code (str): The code that caused the error

        Returns:
            str: Formatted error context for AI
        """
        error_type = type(error).__name__
        error_msg = str(error)
        
        return f"""
The code failed with error:
Error Type: {error_type}
Error Message: {error_msg}

Original Code:
```python
{code}
```

Please fix the code to handle this error. Provide only the corrected code without any explanation.
"""

    def _handle_import_error(self, error: ImportError, code: str) -> Optional[str]:
        """Handle missing package errors by attempting to install them.
        
        Args:
            error (ImportError): The import error
            code (str): The code that caused the error

        Returns:
            Optional[str]: Fixed code or None if installation failed
        """
        try:
            missing_package = str(error).split("'")[1] if "'" in str(error) else str(error).split("No module named")[1].strip()
            missing_package = missing_package.replace("'", "").strip()
            
            console.print(f"Installing missing package: {missing_package}", style="info")
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", missing_package],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                console.print(f"Successfully installed {missing_package}", style="success")
                return code  # Retry with same code after installing package
            else:
                raise Exception(f"Failed to install {missing_package}: {result.stderr}")
        except Exception as e:
            console.print(f"Error installing package: {str(e)}", style="error")
            return None

    def _is_similar_solution(self, new_code: str, threshold: float = 0.8) -> bool:
        """Check if the new solution is too similar to previously tried ones.
        
        Args:
            new_code (str): New solution to check
            threshold (float): Similarity threshold (0-1). Defaults to 0.8.

        Returns:
            bool: True if solution is too similar to previous attempts
        """
        import difflib
        
        def normalize_code(code: str) -> str:
            lines = [line.split('#')[0].strip() for line in code.split('\n')]
            return '\n'.join(line for line in lines if line)
        
        new_code_norm = normalize_code(new_code)
        
        for tried_code in self.tried_solutions:
            tried_code_norm = normalize_code(tried_code)
            similarity = difflib.SequenceMatcher(None, new_code_norm, tried_code_norm).ratio()
            if similarity > threshold:
                return True
        return False

    def main(self, response: str) -> Optional[str]:
        """Execute code with error correction.

        Args:
            response (str): AI response containing code

        Returns:
            Optional[str]: Error message if execution failed, None if successful
        """
        if not response:
            return "No response provided"

        code = self._extract_code_from_response(response)
        if not code:
            return "No executable code found in the response"
        
        ai_instance = self.ai_instance or globals().get('ai')
        
        if not ai_instance:
            console.print("AI instance not found, error correction disabled", style="warning")
            try:
                if self.path_to_script:
                    script_dir = os.path.dirname(self.path_to_script)
                    if script_dir:
                        os.makedirs(script_dir, exist_ok=True)
                    with open(self.path_to_script, "w", encoding="utf-8") as f:
                        f.write(code)
                    
                if self.internal_exec:
                    console.print("[INFO] Executing code internally", style="info")
                    # Create a local namespace
                    local_namespace: Dict[str, Any] = {}
                    
                    # Capture stdout
                    import io
                    old_stdout = sys.stdout
                    captured_output = io.StringIO()
                    sys.stdout = captured_output
                    
                    # Execute the code
                    try:
                        exec(code, globals(), local_namespace)
                        # Capture the result
                        self.last_execution_result = captured_output.getvalue()
                    finally:
                        # Restore stdout
                        sys.stdout = old_stdout
                else:
                    console.print("[INFO] Executing code as external process", style="info")
                    result = subprocess.run(
                        [self.interpreter, self.path_to_script],
                        capture_output=True,
                        text=True
                    )
                    self.last_execution_result = result.stdout
                    
                    if result.returncode != 0:
                        raise Exception(result.stderr or result.stdout)
                        
                return None
            except Exception as e:
                error_msg = f"Execution error: {str(e)}"
                console.print(error_msg, style="error")
                return error_msg
        
        result = self._execute_with_retry(code, ai_instance)
        return result

    @property
    def intro_prompt(self) -> str:
        """Get the introduction prompt.
        
        Returns:
            str: Introduction prompt
        """
        return get_intro_prompt()

    def log(self, message: str, category: str = "info"):
        """RawDog logger

        Args:
            message (str): Log message
            category (str, optional): Log level. Defaults to 'info'.
        """
        if self.quiet:
            return

        message = "[Webscout] - " + message
        if category == "error":
            console.print(f"[ERROR] {message}", style="error")
        else:
            console.print(message, style=category)

    def stdout(self, message: str, style: str = "info") -> None:
        """Enhanced stdout with Rich formatting.

        Args:
            message (str): Text to be printed
            style (str, optional): Style to apply. Defaults to "info".
        """
        if not self.prettify:
            print(message)
            return

        if message.startswith("```") and message.endswith("```"):
            # Handle code blocks
            code = message.strip("`").strip()
            syntax = Syntax(code, "python", theme="monokai", line_numbers=True)
            console.print(Panel(syntax, title="Code", border_style="blue"))
        elif "```python" in message:
            # Handle markdown code blocks
            md = Markdown(message)
            console.print(md)
        else:
            # Handle regular text with optional styling
            console.print(message, style=style)

    def print_code(self, code: str, title: str = "Generated Code") -> None:
        """Print code with syntax highlighting and panel.

        Args:
            code (str): Code to print
            title (str, optional): Panel title. Defaults to "Generated Code".
        """
        if self.prettify:
            syntax = Syntax(code, "python", theme="monokai", line_numbers=True)
            console.print(Panel(
                syntax,
                title=f"[bold blue]In [1]:[/bold blue]",
                border_style="blue",
                expand=True,
                box=ROUNDED
            ))
        else:
            print(f"\n{title}:")
            print(code)

    def print_output(self, output: str, style: str = "output") -> None:
        """Print command output with optional styling.

        Args:
            output (str): Output to print
            style (str, optional): Style to apply. Defaults to "output".
        """
        if self.prettify:
            # Try to detect if output is Python code
            try:
                # If it looks like Python code, syntax highlight it
                compile(output, '<string>', 'exec')
                syntax = Syntax(output, "python", theme="monokai", line_numbers=False)
                formatted_output = syntax
            except SyntaxError:
                # If not Python code, treat as plain text
                formatted_output = output

            console.print(Panel(
                formatted_output,
                title="[bold red]Out [1]:[/bold red]",
                border_style="red",
                expand=True,
                padding=(0, 1),
                box=ROUNDED
            ))
        else:
            print("\nOutput:")
            print(output)

    def print_error(self, error: str) -> None:
        """Print error message with styling.

        Args:
            error (str): Error message to print
        """
        if self.prettify:
            console.print(f"\n Error:", style="error bold")
            console.print(error, style="error")
        else:
            print("\nError:")
            print(error)

    def print_table(self, headers: list, rows: list) -> None:
        """Print data in a formatted table.

        Args:
            headers (list): Table headers
            rows (list): Table rows
        """
        if not self.prettify:
            # Simple ASCII table
            print("\n" + "-" * 80)
            print("| " + " | ".join(headers) + " |")
            print("-" * 80)
            for row in rows:
                print("| " + " | ".join(str(cell) for cell in row) + " |")
            print("-" * 80)
            return

        table = Table(show_header=True, header_style="bold cyan")
        for header in headers:
            table.add_column(header)
        
        for row in rows:
            table.add_row(*[str(cell) for cell in row])
        
        console.print(table)