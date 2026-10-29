<?php

namespace McpHub\Laravel\Contracts;

use Illuminate\Contracts\Auth\Authenticatable;
use McpHub\Laravel\Security\Actor;

interface ActorResolver
{
    public function forUser(Authenticatable $user): Actor;

    /** Re-check current account status and tenant membership on every request. */
    public function resolve(string $userReference, string $tenant): Actor;
}
