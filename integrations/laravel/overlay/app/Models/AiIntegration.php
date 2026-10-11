<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Support\Facades\Crypt;

class AiIntegration extends Model
{
    protected $attributes = ['enabled' => true];

    protected $fillable = [
        'name',
        'api_url',
        'api_key',
        'enabled',
        'permissions',
        'last_used_at',
    ];

    protected $casts = [
        'enabled' => 'boolean',
        'permissions' => 'array',
        'last_used_at' => 'datetime',
    ];

    public static function isEnabled(): bool
    {
        return (bool) static::query()->latest('id')->value('enabled');
    }

    public function permission(string $resource): array
    {
        return (array) (($this->permissions ?? [])[$resource] ?? []);
    }

    public function setApiKeyAttribute($value): void
    {
        if ($value === null || $value === '') {
            return;
        }

        $this->attributes['api_key'] = Crypt::encryptString((string) $value);
    }

    public function getApiKeyAttribute($value): ?string
    {
        if ($value === null || $value === '') {
            return null;
        }

        try {
            return Crypt::decryptString($value);
        } catch (\Throwable $e) {
            if (str_starts_with($value, 'sk-') && $this->exists) {
                $encrypted = Crypt::encryptString($value);
                \Illuminate\Support\Facades\DB::table($this->getTable())
                    ->where('id', $this->getKey())
                    ->where('api_key', $value)
                    ->update(['api_key' => $encrypted]);
                $this->attributes['api_key'] = $encrypted;
                $this->syncOriginalAttribute('api_key');

                return $value;
            }

            return null;
        }
    }

    public function hasApiKey(): bool
    {
        return filled($this->api_key);
    }
}
