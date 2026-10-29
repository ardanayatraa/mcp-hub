<?php

namespace McpHub\Laravel;

use Illuminate\Contracts\Config\Repository;
use Illuminate\Contracts\Encryption\Encrypter;
use RuntimeException;

final class Connection
{
    public function __construct(private Repository $config, private Encrypter $encrypter)
    {
    }

    public function get(string $key, $default = null)
    {
        $value = $this->config->get('mcp-hub.'.$key);
        if ($value !== null && $value !== '') {
            return $value;
        }
        return $this->saved()[$key] ?? $default;
    }

    public function save(array $values): void
    {
        $file = storage_path('app/mcp-hub/connection.enc');
        if (! is_dir(dirname($file)) && ! mkdir(dirname($file), 0700, true) && ! is_dir(dirname($file))) {
            throw new RuntimeException('Connection storage is unavailable.');
        }
        $temporary = $file.'.'.bin2hex(random_bytes(8)).'.tmp';
        try {
            $payload = $this->encrypter->encryptString(json_encode($values, JSON_THROW_ON_ERROR));
            if (file_put_contents($temporary, $payload, LOCK_EX) === false) {
                throw new RuntimeException('Connection could not be saved.');
            }
            chmod($temporary, 0600);
            if (! rename($temporary, $file)) {
                throw new RuntimeException('Connection could not be saved.');
            }
        } finally {
            if (is_file($temporary)) {
                unlink($temporary);
            }
        }
    }

    private function saved(): array
    {
        $file = storage_path('app/mcp-hub/connection.enc');
        if (! is_file($file)) {
            return [];
        }
        $values = json_decode($this->encrypter->decryptString(file_get_contents($file)), true, 16, JSON_THROW_ON_ERROR);
        if (! is_array($values)) {
            throw new RuntimeException('Connection storage is invalid.');
        }
        return $values;
    }
}
