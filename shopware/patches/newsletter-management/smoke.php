<?php declare(strict_types=1);
// Synthetic workflow fixture; deliberately suppresses mail flows in its own context.
$loader = require getcwd() . '/vendor/autoload.php';
(new Symfony\Component\Dotenv\Dotenv())->bootEnv(getcwd() . '/.env');
$kernel = Shopware\Core\Framework\Adapter\Kernel\KernelFactory::create(
    environment: 'prod', debug: false, classLoader: $loader,
    pluginLoader: new Shopware\Core\Framework\Plugin\KernelPluginLoader\DbalKernelPluginLoader(
        $loader, null, Shopware\Core\Kernel::getConnection()
    )
);
$kernel->boot();
$c = $kernel->getContainer();
$context = $c->get(Shopware\Core\System\SalesChannel\Context\SalesChannelContextFactory::class)
    ->create(Shopware\Core\Framework\Uuid\Uuid::randomHex(), '07a1e910ba9a40269c2f70d16066f167');
$context->getContext()->addState(Shopware\Core\Framework\Context::SKIP_TRIGGER_FLOW);
$file = getcwd() . '/var/gc-newsletter-setup/smoke-fixture.json';
$mode = $argv[1] ?? '';
$repo = $c->get('newsletter_recipient.repository');
if ($mode === '--subscribe') {
    if (file_exists($file)) throw new RuntimeException('Previous fixture still exists.');
    $email = 'gc-newsletter-workflow-' . bin2hex(random_bytes(6)) . '@example.invalid';
    $c->get(Shopware\Core\Content\Newsletter\SalesChannel\NewsletterSubscribeRoute::class)
        ->subscribeWithResponse(new Shopware\Core\Framework\Validation\DataBag\RequestDataBag([
            'email' => $email, 'option' => 'subscribe', 'storefrontUrl' => 'https://www.classei-shop.com',
        ]), $context);
    $criteria = (new Shopware\Core\Framework\DataAbstractionLayer\Search\Criteria())
        ->addFilter(new Shopware\Core\Framework\DataAbstractionLayer\Search\Filter\EqualsFilter('email', $email));
    $recipient = $repo->search($criteria, $context->getContext())->first();
    if (!$recipient || $recipient->getStatus() !== 'notSet') throw new RuntimeException('Registration not pending confirmation.');
    umask(0077);
    file_put_contents($file, json_encode(['id' => $recipient->getId(), 'email' => $email]));
    $url = 'https://www.classei-shop.com' . $c->get(Shopware\Core\System\SystemConfig\SystemConfigService::class)->getString('core.newsletter.subscribeUrl', $context->getSalesChannelId());
    if (!is_string($url) || !str_starts_with($url, 'https://www.classei-shop.com/newsletter-subscribe?em=') || str_contains($url, '\\'))
        throw new RuntimeException('Confirmation URL is invalid.');
    echo json_encode(['registration' => 'notSet', 'confirmation_url' => 'OK', 'mail_flows' => 'suppressed', 'fixture' => ['id' => $recipient->getId(), 'email' => $email]]) . PHP_EOL;
    exit;
}
$fixture = json_decode(file_get_contents($file), true, 512, JSON_THROW_ON_ERROR);
$recipient = $repo->search(new Shopware\Core\Framework\DataAbstractionLayer\Search\Criteria([$fixture['id']]), $context->getContext())->first();
if (!$recipient || $recipient->getEmail() !== $fixture['email'] || !str_ends_with($fixture['email'], '@example.invalid')) throw new RuntimeException('Fixture mismatch.');
if ($mode === '--confirm') {
    $c->get(Shopware\Core\Content\Newsletter\SalesChannel\NewsletterConfirmRoute::class)
        ->confirmWithResponse(new Shopware\Core\Framework\Validation\DataBag\RequestDataBag([
            'hash' => $recipient->getHash(), 'em' => hash('sha1', $recipient->getEmail()),
        ]), $context);
} elseif ($mode === '--unsubscribe') {
    $c->get(Shopware\Core\Content\Newsletter\SalesChannel\NewsletterUnsubscribeRoute::class)
        ->unsubscribeWithResponse(new Shopware\Core\Framework\Validation\DataBag\RequestDataBag(['email' => $fixture['email']]), $context);
} elseif ($mode === '--cleanup') {
    $repo->delete([['id' => $fixture['id']]], $context->getContext());
    unlink($file);
    echo 'Synthetic Shopware fixture removed.' . PHP_EOL;
    exit;
} else { throw new RuntimeException('Expected --subscribe, --confirm, --unsubscribe or --cleanup.'); }
$recipient = $repo->search(new Shopware\Core\Framework\DataAbstractionLayer\Search\Criteria([$fixture['id']]), $context->getContext())->first();
$expected = $mode === '--confirm' ? 'optIn' : 'optOut';
if ($recipient->getStatus() !== $expected) throw new RuntimeException('Unexpected subscription status.');
echo json_encode(['status' => $recipient->getStatus(), 'mail_flows' => 'suppressed']) . PHP_EOL;
