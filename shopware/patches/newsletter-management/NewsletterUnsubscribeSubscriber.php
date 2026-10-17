<?php declare(strict_types=1);

namespace ClasseiShopTheme\Subscriber;

use Shopware\Core\Framework\Routing\KernelListenerPriorities;
use Shopware\Core\PlatformRequest;
use Symfony\Component\EventDispatcher\EventSubscriberInterface;
use Symfony\Component\HttpKernel\Event\ControllerEvent;
use Symfony\Component\HttpKernel\KernelEvents;

final class NewsletterUnsubscribeSubscriber implements EventSubscriberInterface
{
    public static function getSubscribedEvents(): array
    {
        // Run immediately before Shopware's captcha validation.
        return [KernelEvents::CONTROLLER => ['onController', KernelListenerPriorities::KERNEL_CONTROLLER_EVENT_SCOPE_VALIDATE_PRE]];
    }

    public function onController(ControllerEvent $event): void
    {
        $request = $event->getRequest();
        if (!$event->isMainRequest()
            || !$request->isMethod('POST')
            || $request->attributes->get('_route') !== 'frontend.form.newsletter.register.handle'
            || $request->request->get('option') !== 'unsubscribe') {
            return;
        }

        // Core unsubscribe handling still validates email and rate-limits requests.
        // Never apply this exception to registration, other forms or GET requests.
        $request->attributes->set(PlatformRequest::ATTRIBUTE_CAPTCHA, false);
    }
}
