"""Tests for the s-expression helpers."""

from __future__ import annotations

from kicad_revive.sexpr import Writer, find_blocks, quote, reindent


class TestQuote:
    def test_escapes_newline_rather_than_emitting_it(self):
        # A literal newline inside a quoted atom makes KiCad reject the entire
        # file, and the parse error names only the file -- so this is the
        # single most expensive escaping mistake available.
        assert quote("a\nb") == "a\\nb"
        assert "\n" not in quote("multi\nline\ntext")

    def test_escapes_double_quotes(self):
        assert quote('say "hi"') == 'say \\"hi\\"'

    def test_escapes_backslashes(self):
        assert quote("C:\\path") == "C:\\\\path"

    def test_backslash_escaped_before_quote(self):
        # Order matters: escaping quotes first would then double the escape
        # backslash that was just introduced.
        assert quote('\\"') == '\\\\\\"'

    def test_escapes_tab(self):
        assert quote("a\tb") == "a\\tb"

    def test_leaves_ordinary_text_alone(self):
        assert quote("VOUT") == "VOUT"


class TestFindBlocks:
    def test_finds_balanced_blocks(self):
        text = '(root (symbol "A" (x 1)) (symbol "B" (y 2)))'
        blocks = list(find_blocks(text, '(symbol "'))
        assert blocks == ['(symbol "A" (x 1))', '(symbol "B" (y 2))']

    def test_ignores_parens_inside_strings(self):
        text = '(root (symbol "A)(B" (x 1)))'
        assert list(find_blocks(text, '(symbol "')) == ['(symbol "A)(B" (x 1))']

    def test_ignores_escaped_quote_inside_string(self):
        text = '(root (symbol "A\\"B" (x 1)))'
        assert len(list(find_blocks(text, '(symbol "'))) == 1

    def test_depth_filter_excludes_nested_matches(self):
        text = '(root (symbol "outer" (symbol "inner" (x 1))))'
        top = list(find_blocks(text, '(symbol "', depth=1))
        assert len(top) == 1
        assert top[0].startswith('(symbol "outer"')

    def test_unterminated_block_is_skipped(self):
        assert list(find_blocks('(root (symbol "A" (x 1)', '(symbol "')) == []


class TestReindent:
    def test_shifts_block_preserving_relative_depth(self):
        block = "\t(symbol\n\t\t(pin)\n\t)"
        assert reindent(block, 2) == "\t\t(symbol\n\t\t\t(pin)\n\t\t)"

    def test_empty_block(self):
        assert reindent("", 2) == ""


class TestWriter:
    def test_indents_by_level(self):
        writer = Writer()
        writer.line("(a")
        writer.line("(b)", 1)
        writer.line(")")
        assert writer.render() == "(a\n\t(b)\n)\n"

    def test_raw_is_passed_through_untouched(self):
        writer = Writer()
        writer.raw("\t\t(already indented)")
        assert writer.render() == "\t\t(already indented)\n"
