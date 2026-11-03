# Client, tools, dan profil akses

Client key membatasi pemanggil ke aplikasi dan operasi tertentu. Ia tidak menggantikan identitas pengguna sumber.

## Sambungkan MCP client

Buat key di Access, simpan token satu kali pada secret store client, lalu gunakan endpoint Streamable HTTP:

```json
{
  "mcpServers": {
    "mcp-hub": {
      "type": "http",
      "url": "https://hub.example.com/mcp",
      "headers": {"Authorization": "Bearer <CLIENT_KEY>"}
    }
  }
}
```

Format wrapper bisa berbeda antar client. Untuk resource per pengguna, trusted server juga mengirim `X-Hub-Delegation`. User ID dalam percakapan tidak dapat menetapkan identitas.

## Katalog tools

| Tool | Fungsi |
|---|---|
| `list_data_sources` | Resource dan field yang boleh dilihat |
| `run_report` | Filter, record, total, grouped metrics dengan batas waktu/record |
| Memory tools | Recall/save/forget per pengguna bila diaktifkan |

Tools manual mengikuti draft → test → publish. Tools mode source mengikuti grants manifest. Gunakan **Tools → What the agent sees** untuk memeriksa katalog dari sisi key tertentu. Listing bukan otorisasi permanen; setiap call memeriksa ulang.

## Profil

Akses efektif adalah irisan izin aplikasi, grants resource, profil, allowlist key, dan write scope. Profil tidak dapat membuka field yang dilarang developer atau memperbesar budget model. Daftar profil kosong memberi nol akses pada dimensi tersebut; profil disabled memblokir key terikat pada panggilan berikutnya.

Uji pencabutan dengan data sintetis: panggil tool sah, cabut izin, lalu ulangi. Call harus ditolak walaupun client masih menyimpan katalog lama.

[Referensi tools/reporting](../reference/tools.md) · [API profil dan revision](../reference/profiles.md)
