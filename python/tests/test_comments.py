"""fmt preserves comments (found in the GUI test pass: the extension is
the default formatter now, and format-on-save must never eat notes)."""

import prior_lang


def test_comments_survive_fmt():
    src = (
        "# top note about the whole file\n"
        "universe [sp_top_30]\n\n"
        "# why this entry works\n"
        "when [macd_cross_up]\n"
        "  buy [5% portfolio]\n\n"
        "sell when [after 5 bars]  # time stop\n"
    )
    out = prior_lang.format_source(src)
    assert "# top note about the whole file" in out
    assert "# why this entry works" in out
    assert "# time stop" in out
    # comments sit ABOVE their statements
    assert out.index("# why this entry works") < out.index("when [macd_cross_up]")


def test_comments_follow_reordered_statements():
    # exit written before universe: canonical order moves them; comments ride along
    src = (
        "# about the exit\n"
        "sell when [after 5 bars]\n"
        "# about the universe\n"
        "universe [sp_top_30]\n"
        "when [macd_cross_up]\n  buy [5% portfolio]\n"
    )
    out = prior_lang.format_source(src)
    assert out.index("# about the universe") < out.index("universe [sp_top_30]")
    assert out.index("# about the exit") < out.index("sell when")
    assert out.index("universe [sp_top_30]") < out.index("sell when")  # canonical order held


def test_fmt_is_idempotent_with_comments():
    src = (
        "# note\nuniverse [sp_top_30]\nwhen [rsi] < 30\n  buy [5% portfolio]\n"
        "sell when [after 5 bars]\n# trailing thought\n"
    )
    once = prior_lang.format_source(src)
    twice = prior_lang.format_source(once)
    assert once == twice
    assert "# trailing thought" in once


def test_strip_comments_option():
    from prior_lang.formatter import format_program
    from prior_lang import parse_source
    src = "# gone\nuniverse [sp_top_30]\nwhen [rsi] < 30\n  buy [5% portfolio]\nsell when [after 5 bars]\n"
    out = format_program(parse_source(src), include_comments=False)
    assert "#" not in out
    assert "universe [sp_top_30]" in out


def test_examples_keep_their_docs():
    from pathlib import Path
    for path in sorted((Path(__file__).parents[2] / "examples").glob("*.prior")):
        src = path.read_text()
        n_comments = sum(1 for l in src.splitlines() if l.strip().startswith("#"))
        if n_comments == 0:
            continue
        out = prior_lang.format_source(src)
        kept = sum(1 for l in out.splitlines() if l.strip().startswith("#"))
        assert kept == n_comments, f"{path.name}: {n_comments} comments -> {kept}"
        assert prior_lang.compile_source(out) == prior_lang.compile_source(src), path.name
