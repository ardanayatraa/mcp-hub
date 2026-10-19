<?php

namespace App\Services\Mcp;

use App\Models\User;
use Illuminate\Support\Facades\Cache;
use RuntimeException;

class McpActorIdentity
{
    public static function active(User $user): User
    {
        $fresh = User::query()->whereKey($user->getKey())->first();
        if (! $fresh || ! self::accountEnabled($fresh)) {
            throw new RuntimeException('Hub user access denied.');
        }
        return $fresh;
    }

    private static function accountEnabled(User $user): bool
    {
        if ($user->status === 'active') { return true; }
        // Registration leaves status null. Accept legacy accounts only with an
        // explicitly active, selected source role; recheck it on every request.
        if ($user->status !== null) { return false; }
        $roles = \App\Models\RoleUser::query()->where('user_id', $user->getKey());
        if ((clone $roles)->where('status', 'active')->where('active', 1)->exists()) { return true; }
        // UserIsValid permits ordinary customers without an administrative role.
        // Do not let an inactive role or unassigned super-admin use that fallback.
        return ! $roles->exists() && ! $user->super()->where('role', 'superadmin')->exists();
    }

    public static function tenant(User $user): string
    {
        // Current User means this account's own records, not all team records.
        return 'hireach_account_'.$user->getKey();
    }

    public static function sign(User $user, string $audience): string
    {
        $secret = (string) config('ai.mcp.hub.delegation_secret');
        if (strlen($secret) < 32) {
            throw new RuntimeException('Hub delegation is not configured.');
        }
        $payload = ['app_key' => 'hireach', 'aud' => $audience, 'exp' => time() + 90, 'jti' => self::encode(random_bytes(18)),
            'tenant_id' => self::tenant($user), 'user_ref' => 'hireach_user_'.$user->getKey()];
        ksort($payload);
        $raw = json_encode($payload, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES);
        return self::encode($raw).'.'.self::encode(hash_hmac('sha256', $raw, $secret, true));
    }

    public static function verify(string $token): User
    {
        $secret = (string) config('ai.mcp.hub.delegation_secret');
        if (strlen($secret) < 32 || strlen($token) > 4096 || substr_count($token, '.') !== 1) {
            throw new RuntimeException('Hub assertion denied.');
        }
        [$body, $signature] = explode('.', $token, 2);
        $raw = self::decode($body);
        if (! hash_equals(hash_hmac('sha256', $raw, $secret, true), self::decode($signature))) {
            throw new RuntimeException('Hub assertion denied.');
        }
        $payload = json_decode($raw, true, 8, JSON_THROW_ON_ERROR);
        if (! is_array($payload) || ($payload['app_key'] ?? '') !== 'hireach'
            || ($payload['aud'] ?? '') !== config('ai.mcp.hub.source_url')
            || ! is_int($payload['exp'] ?? null) || $payload['exp'] <= time() || $payload['exp'] > time() + 150
            || ! is_string($payload['user_ref'] ?? null)
            || ! preg_match('/^hireach_user_([1-9][0-9]{0,9})$/D', $payload['user_ref'], $match)
            || ! is_string($payload['jti'] ?? null) || ! preg_match('/^[A-Za-z0-9_-]{16,64}$/D', $payload['jti'])) {
            throw new RuntimeException('Hub assertion denied.');
        }
        $user = User::query()->find((int) $match[1]);
        if (! $user || ! self::accountEnabled($user) || ($payload['tenant_id'] ?? '') !== self::tenant($user)) {
            throw new RuntimeException('Hub user access denied.');
        }
        // One use only: a captured assertion cannot be replayed while it is still valid (atomic add).
        if (! Cache::add('hireach.hub.assertion.'.hash('sha256', $payload['jti']), 1, $payload['exp'] - time() + 5)) {
            throw new RuntimeException('Hub assertion denied.');
        }
        return $user;
    }

    private static function encode(string $value): string
    {
        return rtrim(strtr(base64_encode($value), '+/', '-_'), '=');
    }

    private static function decode(string $value): string
    {
        if (! preg_match('/^[A-Za-z0-9_-]+$/D', $value)) {
            throw new RuntimeException('Hub assertion denied.');
        }
        $decoded = base64_decode(strtr($value, '-_', '+/'), true);
        if ($decoded === false) {
            throw new RuntimeException('Hub assertion denied.');
        }
        return $decoded;
    }
}
