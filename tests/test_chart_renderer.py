import os
import tempfile
import unittest

from core.chart_renderer import normalize_mermaid, parse_xychart, render_chart


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


if __name__ == "__main__":
    unittest.main()
