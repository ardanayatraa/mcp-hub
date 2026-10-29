<?php

namespace McpHub\Laravel\Security;

use Illuminate\Contracts\Auth\Authenticatable;
use McpHub\Laravel\Contracts\ActorResolver;
use RuntimeException;

final class DenyActorResolver implements ActorResolver
{
    public function forUser(Authenticatable $user): Actor
    {
        throw new RuntimeException('The application has not configured an actor resolver.');
    }

    public function resolve(string $userReference, string $tenant): Actor
    {
        throw new RuntimeException('Actor access denied.');
    }
}
