import pandas as pd
from app.database import get_connection

POS_FILE = "data/resources/pos_transactions.csv"

def get_pos_metrics():
    df = pd.read_csv(POS_FILE)

    transaction_count = len(df)
    total_revenue = round(df["total_amount"].sum(), 2)
    average_order_value = round(df["total_amount"].mean(), 2)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT COUNT(DISTINCT visitor_id) FROM events WHERE is_staff=0"
    )
    unique_visitors = cursor.fetchone()[0] or 0
    conn.close()

    conversion_rate = 0
    revenue_per_visitor = 0

    if unique_visitors > 0:
        conversion_rate = round(transaction_count / unique_visitors, 2)
        revenue_per_visitor = round(total_revenue / unique_visitors, 2)

    return {
        "unique_visitors": unique_visitors,
        "transactions": transaction_count,
        "revenue": total_revenue,
        "average_order_value": average_order_value,
        "conversion_rate": conversion_rate,
        "revenue_per_visitor": revenue_per_visitor
    }