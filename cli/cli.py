"""Stella CLI entry point."""

import click
from cli import __version__
from cli.commands.skill import skill
from cli.commands.context import context
from cli.commands.install import install_browser
from cli.commands.knowledge import knowledge
from cli.commands.backup import backup_command, restore_command


HELP_TEXT = """Usage: stella COMMAND [ARGS]...

  Stella CLI - Manage your Stella instance.

Commands:
  help     Show this message.
  version  Show the version.
  skill    Manage Stella skills.
  knowledge  Manage knowledge base.
  backup   Back up config and agent workspace.
  restore  Restore a Stella backup.
  install-browser  Install browser tool (Playwright + Chromium).

Tip: Memory index management lives in chat — send /memory status or
/memory rebuild-index to the running agent. The Electron client manages the
backend process."""


class StellaCLI(click.Group):

    def format_help(self, ctx, formatter):
        formatter.write(HELP_TEXT.strip())
        formatter.write("\n")

    def parse_args(self, ctx, args):
        if args and args[0] == 'help':
            click.echo(HELP_TEXT.strip())
            ctx.exit(0)
        return super().parse_args(ctx, args)


@click.group(cls=StellaCLI, invoke_without_command=True, context_settings=dict(help_option_names=[]))
@click.pass_context
def main(ctx):
    """Stella CLI - Manage your Stella instance."""
    if ctx.invoked_subcommand is None:
        click.echo(HELP_TEXT.strip())


@main.command()
def version():
    """Show the version."""
    click.echo(f"stella {__version__}")


@main.command(name='help')
@click.pass_context
def help_cmd(ctx):
    """Show this message."""
    click.echo(HELP_TEXT.strip())


main.add_command(skill)
main.add_command(context)
main.add_command(knowledge)
main.add_command(backup_command)
main.add_command(restore_command)
main.add_command(install_browser)


if __name__ == '__main__':
    main()
