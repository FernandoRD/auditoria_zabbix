import os
import math
import tempfile
import unittest

from core.chart_renderer import normalize_mermaid, parse_pie, parse_xychart, render_chart


class TestNormalizeMermaid(unittest.TestCase):
    def test_fixes_linechart_hallucination(self):
        code = "lineChart\n  title \"X\"\n  line [1,2]"
        result = normalize_mermaid(code, "line")
        self.assertTrue(result.startswith("xychart-beta"))

    def test_fixes_barchart_hallucination(self):
        code = "barChart\n  title \"X\"\n  bar [1,2]"
        result = normalize_mermaid(code, "bar")
        self.assertTrue(result.startswith("xychart-beta"))

    def test_fixes_data_colon_hallucination(self):
        code = "xychart-beta\n  data: [1,2,3]"
        result = normalize_mermaid(code, "line")
        self.assertIn("line [1,2,3]", result)
        self.assertNotIn("data:", result)

    def test_forces_series_type_to_user_selection(self):
        code = "xychart-beta\n  bar [1,2,3]"
        result = normalize_mermaid(code, "line")
        self.assertIn("line [1,2,3]", result)

    def test_leaves_correct_syntax_unchanged_in_content(self):
        code = "xychart-beta\n  title \"X\"\n  line [1,2,3]"
        result = normalize_mermaid(code, "line")
        self.assertIn('title "X"', result)
        self.assertIn("line [1,2,3]", result)


class TestParseXychart(unittest.TestCase):
    def test_canonical_prompt_example(self):
        code = (
            'xychart-beta\n'
            '  title "Nome da Métrica"\n'
            '  x-axis ["T1", "T2", "T3", "T4"]\n'
            '  y-axis "Valores"\n'
            '  line [10, 20, 15, 30]'
        )
        result = parse_xychart(code)
        self.assertEqual(result["title"], "Nome da Métrica")
        self.assertEqual(result["x_labels"], ["T1", "T2", "T3", "T4"])
        self.assertEqual(result["y_label"], "Valores")
        self.assertIsNone(result["y_range"])
        self.assertEqual(result["series"], [{"type": "line", "values": [10.0, 20.0, 15.0, 30.0]}])
        self.assertEqual([], result["warnings"])

    def test_y_axis_with_range(self):
        code = (
            'xychart-beta\n'
            '  title "Cache"\n'
            '  x-axis ["1h", "45m"]\n'
            '  y-axis "Uso de Cache (%)" 0 --> 100\n'
            '  bar [20, 35]'
        )
        result = parse_xychart(code)
        self.assertEqual(result["y_label"], "Uso de Cache (%)")
        self.assertEqual(result["y_range"], (0.0, 100.0))
        self.assertEqual(result["series"], [{"type": "bar", "values": [20.0, 35.0]}])

    def test_multiple_series(self):
        code = (
            'xychart-beta\n'
            '  title "Multi"\n'
            '  x-axis ["a","b"]\n'
            '  y-axis "V"\n'
            '  line [1,2]\n'
            '  bar [3,4]'
        )
        result = parse_xychart(code)
        self.assertEqual(result["series"], [
            {"type": "line", "values": [1.0, 2.0]},
            {"type": "bar", "values": [3.0, 4.0]},
        ])

    def test_non_xychart_returns_none(self):
        code = "flowchart TD\n  A --> B"
        self.assertIsNone(parse_xychart(code))

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_xychart("isto não é mermaid nenhum"))

    def test_xychart_without_series_returns_none(self):
        code = 'xychart-beta\n  title "Vazio"\n  x-axis ["a"]\n  y-axis "V"'
        self.assertIsNone(parse_xychart(code))

    def test_invalid_point_becomes_nan_without_discarding_series(self):
        result = parse_xychart(
            'xychart-beta\n  x-axis ["a","b","c","d"]\n'
            '  line [1, N/A, , 4]'
        )

        values = result["series"][0]["values"]
        self.assertEqual(4, len(values))
        self.assertEqual(1.0, values[0])
        self.assertTrue(math.isnan(values[1]))
        self.assertTrue(math.isnan(values[2]))
        self.assertEqual(4.0, values[3])

    def test_all_invalid_series_is_retained_with_warning(self):
        result = parse_xychart('xychart-beta\n  line [N/A, vazio]')

        self.assertEqual(1, len(result["series"]))
        self.assertIn("totalmente inválida", result["warnings"][0])


class TestParsePie(unittest.TestCase):
    def test_valid_pie(self):
        result = parse_pie(
            'pie showData\n  title "Problemas"\n  "Alta" : 8\n  "Baixa" : 2'
        )

        self.assertEqual("pie", result["chart_type"])
        self.assertEqual(["Alta", "Baixa"], result["labels"])
        self.assertEqual([8.0, 2.0], result["values"])

    def test_invalid_or_empty_pie_returns_none(self):
        self.assertIsNone(parse_pie('pie\n  "Alta" : N/A'))
        self.assertIsNone(parse_pie('pie\n  "Alta" : -1'))
        self.assertIsNone(parse_pie('flowchart TD\n A --> B'))


class TestRenderChart(unittest.TestCase):
    def setUp(self):
        self.chart = {
            "title": "Teste",
            "x_labels": ["a", "b", "c"],
            "y_label": "V",
            "y_range": None,
            "series": [{"type": "line", "values": [1.0, 5.0, 3.0]}],
        }
        self.tmpdir = tempfile.mkdtemp(prefix="chart_renderer_test_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_renders_png_with_default_style(self):
        output_path = os.path.join(self.tmpdir, "default.png")
        render_chart(self.chart, {}, output_path)
        self.assertTrue(os.path.exists(output_path))
        self.assertGreater(os.path.getsize(output_path), 0)

    def test_renders_bar_chart_with_custom_style(self):
        chart = dict(self.chart, series=[{"type": "bar", "values": [4.0, 8.0, 2.0]}])
        style = {
            "chart_color": "Azul",
            "chart_bg_color": "Transparente",
            "chart_text_color": "Branco",
            "chart_width": 1000,
            "chart_height": 500,
            "chart_font": "Verdana, Geneva, sans-serif",
        }
        output_path = os.path.join(self.tmpdir, "custom.png")
        render_chart(chart, style, output_path)
        self.assertTrue(os.path.exists(output_path))
        self.assertGreater(os.path.getsize(output_path), 0)

    def test_renders_multi_series_with_y_range(self):
        chart = dict(
            self.chart,
            y_range=(0.0, 10.0),
            series=[
                {"type": "line", "values": [1.0, 2.0, 3.0]},
                {"type": "line", "values": [3.0, 2.0, 1.0]},
            ],
        )
        output_path = os.path.join(self.tmpdir, "multi.png")
        render_chart(chart, {}, output_path)
        self.assertTrue(os.path.exists(output_path))
        self.assertGreater(os.path.getsize(output_path), 0)

    def test_does_not_raise_for_unknown_style_values(self):
        style = {"chart_color": "Cor Inexistente", "chart_bg_color": "Nada", "chart_text_color": "Nada"}
        output_path = os.path.join(self.tmpdir, "fallback.png")
        render_chart(self.chart, style, output_path)
        self.assertTrue(os.path.exists(output_path))

    def test_renders_with_short_and_long_label_lists(self):
        short = dict(self.chart, x_labels=["apenas um"])
        long = dict(self.chart, x_labels=["a", "b", "c", "extra"])
        for name, chart in (("short.png", short), ("long.png", long)):
            output_path = os.path.join(self.tmpdir, name)
            render_chart(chart, {}, output_path)
            self.assertGreater(os.path.getsize(output_path), 0)

    def test_renders_isolated_nan_and_multiple_bar_series(self):
        chart = dict(
            self.chart,
            series=[
                {"type": "bar", "values": [1.0, math.nan, 3.0]},
                {"type": "bar", "values": [2.0, 4.0, math.nan]},
            ],
        )
        output_path = os.path.join(self.tmpdir, "nan_multi.png")
        render_chart(chart, {}, output_path)
        self.assertGreater(os.path.getsize(output_path), 0)

    def test_renders_pie(self):
        chart = parse_pie('pie showData\n  title "Tipos"\n  "A" : 3\n  "B" : 7')
        output_path = os.path.join(self.tmpdir, "pie.png")
        render_chart(chart, {}, output_path)
        self.assertGreater(os.path.getsize(output_path), 0)


if __name__ == "__main__":
    unittest.main()
