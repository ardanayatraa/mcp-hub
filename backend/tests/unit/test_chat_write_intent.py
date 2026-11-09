import pytest
from app.chat.engine import _explicit_write_intent


@pytest.mark.parametrize("text", [
    "Tolong buatkan pesanan baru: 2 kopi lewat kanal online.",
    "Buat pesanan baru untuk SKU KOP-001",
    "bikinin order 2 teh tarik",
    "Tambahin stok sabun 10",
    "tambahkan produk baru",
    "Batalkan pesanan ORD-123",
    "ubah status pesanan jadi paid",
    "Ganti jumlahnya jadi 3",
    "Hapus pesanan ORD-9",
    "tandai pesanan ORD-1 sudah dibayar",
    "Masukkan pesanan baru dari marketplace",
    "catat penjualan hari ini",
    "Update status ORD-1 to shipped",
    "Please cancel order ORD-7",
    "Mark ORD-1 as paid",
    "Create an order for two coffees",
])
def test_write_requests_offer_write_tools(text):
    assert _explicit_write_intent(text)


@pytest.mark.parametrize("text", [
    "Pesanan saya yang statusnya paid ada berapa, dan berapa total nilainya?",
    "Produk apa saja yang stoknya habis?",
    "Tampilkan daftar pesanan yang batal",
    "Pesanan masuk hari ini ada berapa?",
    "Ada catatan apa di pesanan ORD-1?",
    "Berapa pesanan yang dibuat minggu ini?",
    "Show me the cancelled orders",
    'Apa arti status "hapus" di laporan?',
])
def test_read_questions_keep_write_tools_hidden(text):
    assert not _explicit_write_intent(text)
