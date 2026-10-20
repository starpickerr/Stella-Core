"""stella knowledge — presentation over the public knowledge service."""
import json
import click
from core.services.knowledge_facade import call


@click.group(invoke_without_command=True)
@click.pass_context
def knowledge(ctx):
    """Manage Stella knowledge base."""
    if ctx.invoked_subcommand is None:
        click.echo(_stats())


@knowledge.command('list')
def knowledge_list():
    """Display the knowledge file tree."""
    click.echo(_tree())


def _stats():
    return json.dumps(call('list_tree')['stats'], ensure_ascii=False, indent=2)


def _tree():
    return json.dumps(call('list_tree'), ensure_ascii=False, indent=2)
