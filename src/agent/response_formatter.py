"""
Structured Response Formatter
Normalizes assistant responses, extracts validated chart configs from executed tools,
aggregates key metrics, and formats data quality notes adhering to API contracts.
"""

from typing import Any, Dict, List, Optional
from src.schemas.chat import AssistantResponse

class ResponseFormatter:
    """Normalizes and validates AssistantResponse payloads."""

    @staticmethod
    def extract_chart_from_tools(executed_tools: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Extract chart configuration directly from the output of an executed chart tool.
        Preserves actual tool execution instead of post-hoc guessing.
        """
        chart_tool_names = {
            "aggregate_energy_telemetry",
            "create_breakdown_chart",
            "create_time_series_chart",
            "create_shift_comparison_chart",
            "create_demand_utilization_gauge",
            "create_correlation_scatter_plot",
            "create_load_heatmap"
        }

        for tool in reversed(executed_tools):
            name = tool.get("name")
            output = tool.get("output")
            if name in chart_tool_names and isinstance(output, dict):
                if "chart_config" in output:
                    return output["chart_config"]
                if "chart_type" in output:
                    return output
            elif isinstance(output, dict):
                if "chart_config" in output:
                    return output["chart_config"]
                if "chart_type" in output:
                    return output
        return None

    @staticmethod
    def extract_metrics_from_tools(executed_tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate key quantitative metrics from executed energy tools."""
        metrics: Dict[str, Any] = {}
        for tool in executed_tools:
            output = tool.get("output")
            if not isinstance(output, dict):
                continue
            # Energy consumption
            if "energy_kwh" in output and output["energy_kwh"] is not None:
                metrics["total_kwh"] = output["energy_kwh"]
            # Shifts
            for s in ("shift_a_kwh", "shift_b_kwh", "shift_c_kwh", "total_shifts_kwh"):
                if s in output and output[s] is not None:
                    metrics[s] = output[s]
            # Demand
            if "peak_kva" in output and output["peak_kva"] is not None:
                metrics["peak_kva"] = output["peak_kva"]
            if "utilization_percent" in output and output["utilization_percent"] is not None:
                metrics["utilization_pct"] = output["utilization_percent"]
            if "contracted_demand_kva" in output and output["contracted_demand_kva"] is not None:
                metrics["contracted_kva"] = output["contracted_demand_kva"]
            # Cost
            if "total_cost_inr" in output and output["total_cost_inr"] is not None:
                metrics["total_cost_inr"] = output["total_cost_inr"]
            if "true_daily_kwh" in output and output["true_daily_kwh"] is not None:
                metrics["total_kwh"] = output["true_daily_kwh"]
            # DG
            if "runtime_hours" in output:
                metrics["dg_runtime_hours"] = output["runtime_hours"]
            if "energy_generated_kwh" in output:
                metrics["dg_energy_kwh"] = output["energy_generated_kwh"]
            # Live telemetry
            if "active_meters" in output:
                metrics["active_meters"] = output["active_meters"]
        return metrics

    @staticmethod
    def extract_data_notes_from_tools(executed_tools: List[Dict[str, Any]]) -> Optional[str]:
        """Extract data quality notes from executed tools."""
        notes = []
        for tool in executed_tools:
            output = tool.get("output")
            if isinstance(output, dict) and output.get("data_quality_notes"):
                notes.append(str(output["data_quality_notes"]))
        return " | ".join(notes) if notes else None

    @classmethod
    def build_assistant_response(
        cls,
        answer_markdown: str,
        executed_tools: List[Dict[str, Any]],
        structured_response: Optional[AssistantResponse] = None
    ) -> AssistantResponse:
        """Construct the final validated AssistantResponse."""
        if structured_response:
            chart = structured_response.chart.model_dump() if hasattr(structured_response.chart, "model_dump") else structured_response.chart
            if not chart:
                chart = cls.extract_chart_from_tools(executed_tools)

            metrics = structured_response.key_metrics or cls.extract_metrics_from_tools(executed_tools)
            notes = structured_response.data_quality_notes or cls.extract_data_notes_from_tools(executed_tools)
            return AssistantResponse(
                answer_markdown=structured_response.answer_markdown or answer_markdown,
                key_metrics=metrics,
                chart=chart,
                data_quality_notes=notes
            )

        chart = cls.extract_chart_from_tools(executed_tools)
        metrics = cls.extract_metrics_from_tools(executed_tools)
        notes = cls.extract_data_notes_from_tools(executed_tools)

        return AssistantResponse(
            answer_markdown=answer_markdown,
            key_metrics=metrics,
            chart=chart,
            data_quality_notes=notes
        )

response_formatter = ResponseFormatter()
