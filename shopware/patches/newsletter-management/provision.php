<?php declare(strict_types=1);
// Run from the confirmed Shopware project root; defaults to inspection only.
$loader = require getcwd() . '/vendor/autoload.php';
(new Symfony\Component\Dotenv\Dotenv())->bootEnv(getcwd() . '/.env');
$pluginLoader = new Shopware\Core\Framework\Plugin\KernelPluginLoader\DbalKernelPluginLoader(
    $loader, null, Shopware\Core\Kernel::getConnection()
);
$kernel = Shopware\Core\Framework\Adapter\Kernel\KernelFactory::create(
    environment: 'prod', debug: false, classLoader: $loader, pluginLoader: $pluginLoader
);
$kernel->boot();
$container = $kernel->getContainer();
$context = Shopware\Core\Framework\Context::createDefaultContext();
$categoryId = 'e27fd608238c4ea19d8a13a7b59972f3';
$channelId = '07a1e910ba9a40269c2f70d16066f167';
$cmsId = 'cb6f2fcbbe5c4600b411651da4f00753';
$parentId = '019d957a6a267c38a32dcaeb84677d33';
$repository = $container->get('category.repository');
$criteria = new Shopware\Core\Framework\DataAbstractionLayer\Search\Criteria([$categoryId]);
$existing = $repository->search($criteria, $context)->first();
if (!in_array('--apply', $argv, true)) {
    echo json_encode(['exists' => $existing !== null, 'categoryId' => $categoryId,
        'url' => 'https://www.classei-shop.com/Newsletter/'], JSON_PRETTY_PRINT) . PHP_EOL;
    exit;
}
if ($existing === null) {
    $repository->create([[
        'id' => $categoryId, 'name' => 'Newsletter', 'active' => true,
        'type' => 'page', 'parentId' => $parentId, 'cmsPageId' => $cmsId,
        'visible' => true, 'description' => 'Newsletter anmelden oder abmelden.',
    ]], $context);
}
$repository->update([['id' => $categoryId, 'slotConfig' => [
    '1407600119d841059b13ec68e23fc7a6' => ['title' => [
        'source' => 'static', 'value' => 'Newsletter anmelden oder abmelden',
    ]],
]]], $context);
$seoRepository = $container->get('seo_url.repository');
$seoCriteria = (new Shopware\Core\Framework\DataAbstractionLayer\Search\Criteria())
    ->addFilter(new Shopware\Core\Framework\DataAbstractionLayer\Search\Filter\EqualsFilter('salesChannelId', $channelId))
    ->addFilter(new Shopware\Core\Framework\DataAbstractionLayer\Search\Filter\EqualsFilter('seoPathInfo', 'Newsletter/'));
$urls = $seoRepository->search($seoCriteria, $context)->getEntities();
foreach ($urls as $url) {
    if ($url->getForeignKey() !== $categoryId) throw new RuntimeException('Newsletter/ is already assigned to another page.');
}
$canonicalCriteria = (new Shopware\Core\Framework\DataAbstractionLayer\Search\Criteria())
    ->addFilter(new Shopware\Core\Framework\DataAbstractionLayer\Search\Filter\EqualsFilter('salesChannelId', $channelId))
    ->addFilter(new Shopware\Core\Framework\DataAbstractionLayer\Search\Filter\EqualsFilter('languageId', $context->getLanguageId()))
    ->addFilter(new Shopware\Core\Framework\DataAbstractionLayer\Search\Filter\EqualsFilter('foreignKey', $categoryId))
    ->addFilter(new Shopware\Core\Framework\DataAbstractionLayer\Search\Filter\EqualsFilter('isCanonical', true));
$canonical = $seoRepository->search($canonicalCriteria, $context)->first();
$seoRepository->upsert([[
    'id' => $canonical?->getId() ?? 'c9c8ab9f450a4ac4b4684acdf3cf0d3a',
    'salesChannelId' => $channelId, 'languageId' => $context->getLanguageId(),
    'foreignKey' => $categoryId, 'routeName' => 'frontend.navigation.page',
    'pathInfo' => '/navigation/' . $categoryId, 'seoPathInfo' => 'Newsletter/',
    'isCanonical' => true, 'isModified' => true, 'isDeleted' => false,
]], $context);
$flowRepository = $container->get('flow.repository');
$flowCriteria = (new Shopware\Core\Framework\DataAbstractionLayer\Search\Criteria(['6617189b44904d16b4505e87e591d144']))
    ->addAssociation('sequences');
$flow = $flowRepository->search($flowCriteria, $context)->first();
if ($flow === null || $flow->getEventName() !== 'newsletter.register') throw new RuntimeException('Expected newsletter confirmation flow missing.');
$confirmationActionExists = false;
foreach ($flow->getSequences() as $sequence) {
    if ($sequence->getActionName() === 'action.mail.send'
        && ($sequence->getConfig()['mailTemplateId'] ?? '') === '6346e977d5cf4bbcafc1bd78f379a9ba') $confirmationActionExists = true;
}
if (!$confirmationActionExists) throw new RuntimeException('Expected double opt-in action missing.');
$container->get(Shopware\Core\System\SystemConfig\SystemConfigService::class)->set(
    'core.newsletter.subscribeUrl', '/newsletter-subscribe?em=%%HASHEDEMAIL%%&hash=%%SUBSCRIBEHASH%%', $channelId
);
$flowRepository->update([['id' => $flow->getId(), 'active' => true]], $context);
echo 'Newsletter page and double opt-in flow configured: https://www.classei-shop.com/Newsletter/' . PHP_EOL;
