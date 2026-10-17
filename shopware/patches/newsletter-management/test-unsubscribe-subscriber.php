<?php declare(strict_types=1);
require getcwd() . '/vendor/autoload.php';
require __DIR__ . '/NewsletterUnsubscribeSubscriber.php';

use ClasseiShopTheme\Subscriber\NewsletterUnsubscribeSubscriber;
use Shopware\Core\Framework\Routing\KernelListenerPriorities;
use Shopware\Core\PlatformRequest;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\HttpFoundation\Response;
use Symfony\Component\HttpKernel\Event\ControllerEvent;
use Symfony\Component\HttpKernel\HttpKernelInterface;
use Symfony\Component\HttpKernel\KernelEvents;

$kernel = new class implements HttpKernelInterface {
    public function handle(Request $request, int $type = self::MAIN_REQUEST, bool $catch = true): Response { return new Response(); }
};
$subscriber = new NewsletterUnsubscribeSubscriber();
$tests = [
    ['POST', 'frontend.form.newsletter.register.handle', 'unsubscribe', HttpKernelInterface::MAIN_REQUEST, false],
    ['POST', 'frontend.form.newsletter.register.handle', 'subscribe', HttpKernelInterface::MAIN_REQUEST, true],
    ['POST', 'frontend.form.newsletter.register.handle', 'direct', HttpKernelInterface::MAIN_REQUEST, true],
    ['POST', 'frontend.form.newsletter.register.handle', '', HttpKernelInterface::MAIN_REQUEST, true],
    ['POST', 'frontend.form.newsletter.register.handle', 'invalid', HttpKernelInterface::MAIN_REQUEST, true],
    ['GET', 'frontend.form.newsletter.register.handle', 'unsubscribe', HttpKernelInterface::MAIN_REQUEST, true],
    ['POST', 'frontend.form.contact.send', 'unsubscribe', HttpKernelInterface::MAIN_REQUEST, true],
    ['POST', 'frontend.form.newsletter.register.handle', 'unsubscribe', HttpKernelInterface::SUB_REQUEST, true],
];
foreach ($tests as [$method, $route, $option, $type, $expected]) {
    $request = Request::create('/form/newsletter', $method, ['option' => $option]);
    $request->attributes->set('_route', $route);
    $request->attributes->set(PlatformRequest::ATTRIBUTE_CAPTCHA, true);
    $event = new ControllerEvent($kernel, static fn () => new Response(), $request, $type);
    $subscriber->onController($event);
    if ($request->attributes->get(PlatformRequest::ATTRIBUTE_CAPTCHA) !== $expected) throw new RuntimeException("Wrong captcha handling for $method $route $option");
}
if (NewsletterUnsubscribeSubscriber::getSubscribedEvents()[KernelEvents::CONTROLLER][1] <= KernelListenerPriorities::KERNEL_CONTROLLER_EVENT_SCOPE_VALIDATE) throw new RuntimeException('Subscriber runs too late.');
echo "9 subscriber checks passed. Registration and other requests retain captcha validation.\n";
