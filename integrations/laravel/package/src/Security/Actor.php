<?php

namespace McpHub\Laravel\Security;

use Illuminate\Contracts\Auth\Authenticatable;
use InvalidArgumentException;

final class Actor
{
    public function __construct(
        public Authenticatable $user,
        public string $reference,
        public string $tenant
    ) {
        if ($reference === '' || $tenant === '' || strlen($reference) > 200 || strlen($tenant) > 200) {
            throw new InvalidArgumentException('Invalid actor context.');
        }
    }
}
