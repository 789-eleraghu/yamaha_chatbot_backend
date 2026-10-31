"""
ClickHouse Query Builder for Yamaha Energy Chatbot
Native ClickHouse queries - no SQLite translation needed.
"""

from typing import List, Tuple


class ClickHouseQueries:
    """
    Native ClickHouse query templates for energy telemetry aggregation.

    Key schema differences from SQLite:
    - tag_daily_energy_rollup uses 'day' column (Date), not 'date' (Text)
    - Energy is computed via: maxMerge(max_value) - minMerge(min_value)
    - opcda_readings.value is String, needs toFloat64OrNull()
    - Uses formatDateTime() instead of strftime()
    - Uses splitByChar() instead of SUBSTR/INSTR
    """

    @staticmethod
    def get_time_bucket_sql(granularity: str) -> Tuple[List[str], str]:
        """
        Return (list of time bucket labels, SQL expression for bucketing).
        """
        g = (granularity or "hourly").lower()

        if "30" in g or "half" in g:
            buckets = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]
            sql_expr = """
                concat(
                    formatDateTime(reading_timestamp, '%H'), ':',
                    if(toInt32(formatDateTime(reading_timestamp, '%M')) < 30, '00', '30')
                )
            """
            return buckets, sql_expr.strip()

        elif "15" in g or "quarter" in g:
            buckets = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 15, 30, 45)]
            sql_expr = """
                concat(
                    formatDateTime(reading_timestamp, '%H'), ':',
                    multiIf(
                        toInt32(formatDateTime(reading_timestamp, '%M')) < 15, '00',
                        toInt32(formatDateTime(reading_timestamp, '%M')) < 30, '15',
                        toInt32(formatDateTime(reading_timestamp, '%M')) < 45, '30',
                        '45'
                    )
                )
            """
            return buckets, sql_expr.strip()

        else:
            # Hourly (default)
            buckets = [f"{h:02d}:00" for h in range(24)]
            sql_expr = "formatDateTime(reading_timestamp, '%H:00')"
            return buckets, sql_expr

    @staticmethod
    def equipment_category_daily(date: str, excluded_tags: List[str]) -> Tuple[str, dict]:
        """
        Single day equipment category breakdown using rollup table.
        Returns total energy per equipment category.
        """
        excluded_list = ", ".join(f"'{t}'" for t in excluded_tags)
        query = f"""
            SELECT
                category,
                ROUND(SUM(tag_energy), 1) as energy_kwh
            FROM (
                SELECT
                    splitByChar('.', tag_id)[1] as category,
                    tag_id,
                    maxMerge(max_value) - minMerge(min_value) as tag_energy
                FROM tag_daily_energy_rollup
                WHERE day = toDate({{date:String}})
                  AND tag_id LIKE '%Energies/Real Energy/Real Energy Into the Load'
                  AND tag_id NOT IN ({excluded_list})
                GROUP BY tag_id
            )
            GROUP BY category
            ORDER BY energy_kwh DESC;
        """
        return query, {"date": date}

    @staticmethod
    def equipment_category_multiday(start_date: str, end_date: str, excluded_tags: List[str]) -> Tuple[str, dict]:
        """
        Multi-day equipment category breakdown with daily granularity.
        """
        excluded_list = ", ".join(f"'{t}'" for t in excluded_tags)
        query = f"""
            SELECT
                toString(day) as date,
                category,
                ROUND(SUM(tag_energy), 1) as energy_kwh
            FROM (
                SELECT
                    day,
                    splitByChar('.', tag_id)[1] as category,
                    tag_id,
                    maxMerge(max_value) - minMerge(min_value) as tag_energy
                FROM tag_daily_energy_rollup
                WHERE day >= toDate({{start_date:String}})
                  AND day <= toDate({{end_date:String}})
                  AND tag_id LIKE '%Energies/Real Energy/Real Energy Into the Load'
                  AND tag_id NOT IN ({excluded_list})
                GROUP BY day, tag_id
            )
            GROUP BY day, category
            ORDER BY day ASC, category;
        """
        return query, {"start_date": start_date, "end_date": end_date}

    @staticmethod
    def equipment_category_hourly(date: str, bucket_sql: str, excluded_tags: List[str]) -> Tuple[str, dict]:
        """
        Single day equipment category with hourly/sub-hourly granularity.
        Uses opcda_readings for sub-daily telemetry.
        """
        excluded_list = ", ".join(f"'{t}'" for t in excluded_tags)
        query = f"""
            SELECT
                category,
                bucket,
                ROUND(SUM(delta), 1) as kwh
            FROM (
                SELECT
                    CASE
                        WHEN splitByChar('.', tag_id)[1] = 'Other' THEN 'Others'
                        ELSE splitByChar('.', tag_id)[1]
                    END as category,
                    tag_id,
                    max(toFloat64OrNull(value)) - min(toFloat64OrNull(value)) as delta,
                    {bucket_sql} as bucket
                FROM opcda_readings
                WHERE reading_timestamp >= parseDateTimeBestEffort({{start_ts:String}})
                  AND reading_timestamp < parseDateTimeBestEffort({{end_ts:String}})
                  AND tag_id LIKE '%Energies/Real Energy/Real Energy Into the Load'
                  AND tag_id NOT IN ({excluded_list})
                GROUP BY tag_id, bucket
            )
            GROUP BY category, bucket
            ORDER BY category, bucket;
        """
        start_ts = f"{date} 00:00:00"
        end_ts = f"{date} 23:59:59"
        return query, {"start_ts": start_ts, "end_ts": end_ts}

    @staticmethod
    def zone_daily(date: str, tag_ids: List[str]) -> Tuple[str, dict]:
        """
        Single zone (cost center) daily energy total.
        """
        tag_list = ", ".join(f"'{t}'" for t in tag_ids)
        query = f"""
            SELECT
                ROUND(SUM(tag_energy), 1) as cc_energy
            FROM (
                SELECT
                    tag_id,
                    maxMerge(max_value) - minMerge(min_value) as tag_energy
                FROM tag_daily_energy_rollup
                WHERE day = toDate({{date:String}})
                  AND tag_id IN ({tag_list})
                GROUP BY tag_id
            );
        """
        return query, {"date": date}

    @staticmethod
    def zone_hourly(date: str, bucket_sql: str, tag_ids: List[str]) -> Tuple[str, dict]:
        """
        Single zone (cost center) with hourly/sub-hourly granularity.
        """
        tag_list = ", ".join(f"'{t}'" for t in tag_ids)
        query = f"""
            SELECT
                bucket,
                ROUND(SUM(delta), 1) as kwh
            FROM (
                SELECT
                    tag_id,
                    max(toFloat64OrNull(value)) - min(toFloat64OrNull(value)) as delta,
                    {bucket_sql} as bucket
                FROM opcda_readings
                WHERE reading_timestamp >= parseDateTimeBestEffort({{start_ts:String}})
                  AND reading_timestamp < parseDateTimeBestEffort({{end_ts:String}})
                  AND tag_id IN ({tag_list})
                GROUP BY tag_id, bucket
            )
            GROUP BY bucket
            ORDER BY bucket ASC;
        """
        start_ts = f"{date} 00:00:00"
        end_ts = f"{date} 23:59:59"
        return query, {"start_ts": start_ts, "end_ts": end_ts}

    @staticmethod
    def zone_multiday(start_date: str, end_date: str, tag_ids: List[str]) -> Tuple[str, dict]:
        """
        Single zone (cost center) multi-day with daily granularity.
        """
        tag_list = ", ".join(f"'{t}'" for t in tag_ids)
        query = f"""
            SELECT
                toString(day) as date,
                ROUND(SUM(tag_energy), 1) as energy_kwh
            FROM (
                SELECT
                    day,
                    tag_id,
                    maxMerge(max_value) - minMerge(min_value) as tag_energy
                FROM tag_daily_energy_rollup
                WHERE day >= toDate({{start_date:String}})
                  AND day <= toDate({{end_date:String}})
                  AND tag_id IN ({tag_list})
                GROUP BY day, tag_id
            )
            GROUP BY day
            ORDER BY day ASC;
        """
        return query, {"start_date": start_date, "end_date": end_date}

    @staticmethod
    def facility_daily(date: str, incomer_tag: str) -> Tuple[str, dict]:
        """
        Facility (main incomer) single day energy.
        """
        query = """
            SELECT
                maxMerge(max_value) - minMerge(min_value) as energy_kwh
            FROM tag_daily_energy_rollup
            WHERE day = toDate({date:String})
              AND tag_id = {tag_id:String}
            GROUP BY tag_id;
        """
        return query, {"date": date, "tag_id": incomer_tag}

    @staticmethod
    def facility_hourly(date: str, bucket_sql: str, incomer_tag: str) -> Tuple[str, dict]:
        """
        Facility (main incomer) hourly/sub-hourly granularity.
        """
        query = f"""
            SELECT
                bucket,
                ROUND(max(toFloat64OrNull(value)) - min(toFloat64OrNull(value)), 1) as kwh
            FROM (
                SELECT
                    toFloat64OrNull(value) as value,
                    {bucket_sql} as bucket
                FROM opcda_readings
                WHERE reading_timestamp >= parseDateTimeBestEffort({{start_ts:String}})
                  AND reading_timestamp < parseDateTimeBestEffort({{end_ts:String}})
                  AND tag_id = {{tag_id:String}}
            )
            GROUP BY bucket
            ORDER BY bucket ASC;
        """
        start_ts = f"{date} 00:00:00"
        end_ts = f"{date} 23:59:59"
        return query, {"start_ts": start_ts, "end_ts": end_ts, "tag_id": incomer_tag}

    @staticmethod
    def facility_multiday(start_date: str, end_date: str, incomer_tag: str) -> Tuple[str, dict]:
        """
        Facility (main incomer) multi-day with daily granularity.
        """
        query = """
            SELECT
                toString(day) as date,
                ROUND(maxMerge(max_value) - minMerge(min_value), 1) as energy_kwh
            FROM tag_daily_energy_rollup
            WHERE day >= toDate({start_date:String})
              AND day <= toDate({end_date:String})
              AND tag_id = {tag_id:String}
            GROUP BY day
            ORDER BY day ASC;
        """
        return query, {"start_date": start_date, "end_date": end_date, "tag_id": incomer_tag}

    @staticmethod
    def specific_tag_daily(date: str, tag_id: str) -> Tuple[str, dict]:
        """
        Specific tag daily energy from rollup.
        """
        query = """
            SELECT
                ROUND(maxMerge(max_value) - minMerge(min_value), 1) as energy_kwh
            FROM tag_daily_energy_rollup
            WHERE day = toDate({date:String})
              AND tag_id = {tag_id:String}
            GROUP BY tag_id;
        """
        return query, {"date": date, "tag_id": tag_id}

    @staticmethod
    def tag_delta_raw(tag_id: str, start_ts: str, end_ts: str) -> Tuple[str, dict]:
        """
        Calculate delta (max - min) for a tag from raw opcda_readings.
        Used when rollup doesn't cover the needed time window.
        """
        query = """
            SELECT
                max(toFloat64OrNull(value)) - min(toFloat64OrNull(value)) as delta
            FROM opcda_readings
            WHERE tag_id = {tag_id:String}
              AND reading_timestamp >= parseDateTimeBestEffort({start_ts:String})
              AND reading_timestamp < parseDateTimeBestEffort({end_ts:String})
              AND toFloat64OrNull(value) > 0;
        """
        return query, {"tag_id": tag_id, "start_ts": start_ts, "end_ts": end_ts}

    @staticmethod
    def search_tags(pattern: str, limit: int = 50) -> Tuple[str, dict]:
        """
        Search for tags matching a pattern.
        """
        query = """
            SELECT DISTINCT tag_id
            FROM tag_daily_energy_rollup
            WHERE tag_id LIKE {pattern:String}
            LIMIT {limit:Int32};
        """
        return query, {"pattern": f"%{pattern}%", "limit": limit}
