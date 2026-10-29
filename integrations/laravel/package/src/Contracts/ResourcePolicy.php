<?php

namespace McpHub\Laravel\Contracts;

use Illuminate\Database\Eloquent\Builder;
use McpHub\Laravel\Security\Actor;

interface ResourcePolicy
{
    public function allows(Actor $actor, string $resource, string $action): bool;

    /** Apply the application's complete record ownership and tenant rules. */
    public function scope(Builder $query, Actor $actor): Builder;
}
