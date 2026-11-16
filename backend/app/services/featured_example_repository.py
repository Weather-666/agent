from __future__ import annotations

import sqlite3
from typing import Any

from app.db import DatabaseConnection
from app.services._sql import execute, fetch_all, fetch_one, rowcount


_EXAMPLE_SELECT = """
    select e.*, c.name as category_name, c.tone as category_tone, u.name as author_name
    from featured_examples e
    join featured_example_categories c on c.id = e.category_id
    left join users u on u.id = e.created_by
"""


class FeaturedExampleRepository:
    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection

    def begin_edit(self) -> None:
        # Serialize this small catalog's editorial transactions, including full-set reorder
        # validation against concurrent inserts/moves/deletes. Market reads and PostgreSQL
        # click updates do not acquire this catalog lock.
        if isinstance(self.connection, sqlite3.Connection):
            if not self.connection.in_transaction:
                execute(self.connection, "begin immediate")
        else:
            execute(
                self.connection,
                "lock table featured_example_categories in share row exclusive mode",
            )

    def categories(self) -> list[dict[str, Any]]:
        return fetch_all(
            self.connection,
            "select * from featured_example_categories order by sort_order, id",
        )

    def category(self, category_id: str) -> dict[str, Any] | None:
        return fetch_one(
            self.connection,
            "select * from featured_example_categories where id = ?",
            (category_id,),
        )

    def create_category(self, category_id: str, name: str, tone: str, now: str) -> None:
        execute(
            self.connection,
            """insert into featured_example_categories
               (id, name, tone, sort_order, created_at, updated_at)
               select ?, ?, ?, coalesce(max(sort_order), -1) + 1, ?, ?
               from featured_example_categories""",
            (category_id, name, tone, now, now),
        )

    def update_category(self, category_id: str, name: str, tone: str, now: str) -> None:
        execute(
            self.connection,
            """update featured_example_categories set name = ?, tone = ?, updated_at = ?
               where id = ?""",
            (name, tone, now, category_id),
        )

    def delete_category(self, category_id: str) -> None:
        execute(
            self.connection, "delete from featured_example_categories where id = ?", (category_id,)
        )

    def order_category(self, category_id: str, position: int, now: str) -> None:
        execute(
            self.connection,
            "update featured_example_categories set sort_order = ?, updated_at = ? where id = ?",
            (position, now, category_id),
        )

    def examples(self, category_id: str | None = None) -> list[dict[str, Any]]:
        where = " where e.category_id = ?" if category_id is not None else ""
        return fetch_all(
            self.connection,
            _EXAMPLE_SELECT + where + " order by c.sort_order, c.id, e.sort_order, e.id",
            (category_id,) if category_id is not None else (),
        )

    def example(self, example_id: str) -> dict[str, Any] | None:
        return fetch_one(self.connection, _EXAMPLE_SELECT + " where e.id = ?", (example_id,))

    def next_example_order(self, category_id: str) -> int:
        row = fetch_one(
            self.connection,
            """select coalesce(max(sort_order), -1) + 1 as position
               from featured_examples where category_id = ?""",
            (category_id,),
        )
        return int(row["position"])

    def create_example(
        self,
        example_id: str,
        category_id: str,
        question: str,
        cycle: int | None,
        actor_id: str,
        now: str,
    ) -> None:
        execute(
            self.connection,
            """insert into featured_examples
               (id, category_id, question, sort_order, review_cycle_days,
                created_by, updated_by, created_at, updated_at)
               values (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                example_id,
                category_id,
                question,
                self.next_example_order(category_id),
                cycle,
                actor_id,
                actor_id,
                now,
                now,
            ),
        )

    def update_example(
        self,
        example_id: str,
        category_id: str,
        question: str,
        cycle: int | None,
        position: int,
        actor_id: str,
        now: str,
    ) -> None:
        execute(
            self.connection,
            """update featured_examples
               set category_id = ?, question = ?, review_cycle_days = ?, sort_order = ?,
                   status = 'pending', reviewed_at = null, reviewed_by = null,
                   expires_at = null, reject_reason = null, updated_by = ?, updated_at = ?
               where id = ?""",
            (category_id, question, cycle, position, actor_id, now, example_id),
        )

    def delete_example(self, example_id: str) -> None:
        execute(self.connection, "delete from featured_examples where id = ?", (example_id,))

    def order_example(self, example_id: str, position: int, actor_id: str, now: str) -> None:
        execute(
            self.connection,
            """update featured_examples set sort_order = ?, updated_by = ?, updated_at = ?
               where id = ?""",
            (position, actor_id, now, example_id),
        )

    def review(
        self,
        example_id: str,
        *,
        expected_updated_at: str,
        status: str,
        actor_id: str,
        reviewed_at: str,
        updated_at: str,
        expires_at: str | None,
        reason: str | None,
    ) -> bool:
        cursor = execute(
            self.connection,
            """update featured_examples
               set status = ?, reviewed_at = ?, reviewed_by = ?, expires_at = ?,
                   reject_reason = ?, updated_by = ?, updated_at = ?
               where id = ? and updated_at = ?""",
            (
                status,
                reviewed_at,
                actor_id,
                expires_at,
                reason,
                actor_id,
                updated_at,
                example_id,
                expected_updated_at,
            ),
        )
        return rowcount(cursor) > 0

    def unlist(self, example_id: str, actor_id: str, now: str) -> None:
        execute(
            self.connection,
            """update featured_examples set status = 'unlisted', updated_by = ?, updated_at = ?
               where id = ?""",
            (actor_id, now, example_id),
        )

    def use(self, example_id: str, now: str) -> dict[str, Any] | None:
        return fetch_one(
            self.connection,
            """update featured_examples set click_count = click_count + 1
               where id = ? and status = 'live' and (expires_at is null or expires_at > ?)
               returning id, question, click_count""",
            (example_id, now),
        )
