<?php

namespace McpHub\Laravel\Security;

use Illuminate\Contracts\Auth\Authenticatable;
use Illuminate\Contracts\Cache\Repository;
use McpHub\Laravel\Connection;
use McpHub\Laravel\Contracts\ActorResolver;
use RuntimeException;

final class Assertions
{
    public function __construct(private Connection $connection, private ActorResolver $resolver, private Repository $cache)
    {
    }

    public function delegate(Authenticatable $user): string
    {
        $actor = $this->resolver->forUser($user);
        $claims = ['app_key' => $this->connection->get('app_key'), 'user_ref' => $actor->reference,
            'tenant_id' => $actor->tenant, 'aud' => 'mcp-hub', 'exp' => time() + 90];
        return $this->sign($claims);
    }

    public function verify(string $token): Actor
    {
        if (strlen($token) > 4096 || substr_count($token, '.') !== 1) {
            throw new RuntimeException('Actor access denied.');
        }
        [$body, $signature] = explode('.', $token, 2);
        $json = $this->decode($body);
        if (! hash_equals(hash_hmac('sha256', $json, $this->secret(), true), $this->decode($signature))) {
            throw new RuntimeException('Actor access denied.');
        }
        $claims = json_decode($json, true, 8, JSON_THROW_ON_ERROR);
        if (! is_array($claims) || ($claims['app_key'] ?? null) !== $this->connection->get('app_key')
            || ($claims['aud'] ?? null) !== $this->connection->get('source_url')
            || ! is_int($claims['exp'] ?? null) || $claims['exp'] <= time() || $claims['exp'] > time() + 150
            || ! is_string($claims['user_ref'] ?? null) || ! is_string($claims['tenant_id'] ?? null)
            || ! is_string($claims['jti'] ?? null) || ! preg_match('/^[A-Za-z0-9_-]{16,64}$/D', $claims['jti'])) {
            throw new RuntimeException('Actor access denied.');
        }
        $actor = $this->resolver->resolve($claims['user_ref'], $claims['tenant_id']);
        if ($actor->reference !== $claims['user_ref'] || $actor->tenant !== $claims['tenant_id']) {
            throw new RuntimeException('Actor access denied.');
        }
        $nonce = 'mcp-hub.assertion.'.hash('sha256', $claims['app_key'].'|'.$claims['jti']);
        if (! $this->cache->add($nonce, true, $claims['exp'] - time() + 5)) {
            throw new RuntimeException('Actor access denied.');
        }
        return $actor;
    }

    private function sign(array $claims): string
    {
        $json = json_encode($claims, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES);
        return $this->encode($json).'.'.$this->encode(hash_hmac('sha256', $json, $this->secret(), true));
    }

    private function secret(): string
    {
        $secret = (string) $this->connection->get('delegation_secret', '');
        if (strlen($secret) < 32) {
            throw new RuntimeException('Delegation secret is not configured.');
        }
        return $secret;
    }

    private function encode(string $raw): string
    {
        return rtrim(strtr(base64_encode($raw), '+/', '-_'), '=');
    }

    private function decode(string $encoded): string
    {
        if (! preg_match('/^[A-Za-z0-9_-]+$/D', $encoded)) {
            throw new RuntimeException('Actor access denied.');
        }
        $raw = base64_decode(strtr($encoded, '-_', '+/'), true);
        if ($raw === false) {
            throw new RuntimeException('Actor access denied.');
        }
        return $raw;
    }
}
