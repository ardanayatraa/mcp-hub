# Resource dan izin

Resource mendefinisikan model, field yang diperbolehkan, filter, serta policy aplikasi. Database tidak diekspos otomatis.

## Temukan kandidat

```bash
php artisan mcp-hub:discover
php artisan mcp-hub:discover --schema
php artisan make:mcp-resource orders --model='App\Models\Order'
```

Discovery membaca metadata, bukan record bisnis. Generator menghasilkan definisi **nonaktif** di `config/mcp-hub-resources`, policy yang menolak akses, dan kelas aplikasi terkait. Tinjau semuanya sebelum mengaktifkan grants.

## Resolver actor

Implementasikan `McpHub\Laravel\Contracts\ActorResolver`:

```php
public function forUser(Authenticatable $user): Actor;
public function resolve(string $userReference, string $tenant): Actor;
```

`forUser` mengambil identitas dari user terautentikasi server. `resolve` memeriksa ulang akun aktif dan keanggotaan tenant untuk reference yang ditandatangani. Kembalikan actor yang konsisten atau tolak akses; identitas tidak diambil dari argumen model.

Contoh berikut mengasumsikan class aplikasi telah diimplementasikan:

```php
'actor_resolver' => \App\Mcp\ActorResolver::class,
'models' => [
    'orders' => [
        'model' => \App\Models\Order::class,
        'policy' => \App\Mcp\OrderPolicy::class,
        'enabled' => true,
        'read' => true,
        'lookup' => 'title',
        'fields' => [
            'title' => 'string',
            'status' => 'string',
            'total' => 'number',
        ],
        'filters' => ['status' => ['paid', 'pending']],
    ],
],
```

## Scope dan policy

`ResourcePolicy` memisahkan izin aksi dari pembatas query:

```php
public function allows(Actor $actor, string $resource, string $action): bool;
public function scope(Builder $query, Actor $actor): Builder;
```

`allows` memeriksa permission saat ini; `scope` membatasi seluruh query menurut tenant, ownership, dan visibilitas host. Nama kolom/role mengikuti aplikasi Anda. Filter UI atau tenant ID dari model bukan batas keamanan.

Uji akun tidak aktif, tenant berbeda, record pengguna lain, dan pencabutan izin. Jangan menambahkan field sensitif ke allowlist. `limit`/`cursor` merupakan parameter pagination yang dicadangkan.

## Reference dan grants

Reference default opaque dan terenkripsi, terikat source/environment/resource/actor/tenant. Reference tidak menggantikan query scope. Grants admin hanya mengurangi batas developer. Key tools wajib muat dalam batas 80 karakter Hub.

Setelah review, sync manifest dan verifikasi katalog dari client terbatas. Lihat [kontrak sumber](../reference/connector-contract.md) untuk schema dan envelope.
