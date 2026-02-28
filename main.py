import click
import asyncio
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from config import get_config
from core.router import UnifiedRouter
from tools.registry import init_tools, get_registry

console = Console()

@click.group()
def cli(): pass

@cli.command()
def chat():
    """Interactive chat"""
    get_config()
    console.print(Panel.fit("[green]Emission Calculation Agent[/green]\nType 'quit' to exit"))

    router = UnifiedRouter(session_id="cli_session")

    async def chat_loop():
        while True:
            user_input = console.input("\n[blue]You:[/blue] ").strip()
            if user_input.lower() == "quit":
                break
            if user_input.lower() == "clear":
                router.clear_history()
                console.print("[yellow]History cleared[/yellow]")
                continue

            with console.status("Thinking..."):
                response = await router.chat(user_message=user_input, file_path=None)

            console.print(f"\n[green]Agent:[/green]")
            console.print(Markdown(response.text))

            # Show chart/table data if available
            if response.chart_data:
                console.print("\n[cyan]Chart data available[/cyan]")
            if response.table_data:
                console.print("\n[cyan]Table data available[/cyan]")
            if response.download_file:
                console.print(f"\n[cyan]Download file: {response.download_file}[/cyan]")

    asyncio.run(chat_loop())

@cli.command()
def health():
    """Health check"""
    get_config()
    init_tools()
    registry = get_registry()
    tools = registry.list_tools()

    console.print(Panel.fit("[cyan]Tool Health Check[/cyan]"))
    for tool_name in tools:
        console.print(f"[green]OK[/green] {tool_name}")

    console.print(f"\nTotal tools: {len(tools)}")

@cli.command()
def tools_list():
    """List available tools"""
    get_config()
    init_tools()
    registry = get_registry()
    tools = registry.list_tools()

    console.print(Panel.fit("[cyan]Available Tools[/cyan]"))
    for tool_name in tools:
        tool = registry.get(tool_name)
        console.print(f"- {tool_name}")

if __name__ == "__main__":
    cli()
