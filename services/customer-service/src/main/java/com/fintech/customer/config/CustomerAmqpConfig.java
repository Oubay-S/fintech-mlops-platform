package com.fintech.customer.config;

import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.core.TopicExchange;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnClass;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
@ConditionalOnClass(TopicExchange.class)
public class CustomerAmqpConfig {

    @Value("${app.messaging.exchange:fintech.events}")
    private String exchangeName;

    @Value("${app.messaging.queues.customer-events:customer.events}")
    private String queueName;

    @Bean
    public TopicExchange fintechEventsExchange() {
        return new TopicExchange(exchangeName, true, false);
    }

    @Bean
    public Queue customerEventsQueue() {
        return new Queue(queueName, true);
    }

    @Bean
    public Binding bindingUserRegistered(Queue customerEventsQueue, TopicExchange fintechEventsExchange) {
        // Receives events from auth service for newly registered users/staff
        return BindingBuilder.bind(customerEventsQueue)
                .to(fintechEventsExchange)
                .with("auth.user.registered");
    }

    @Bean
    public Binding bindingAllAuthEvents(Queue customerEventsQueue, TopicExchange fintechEventsExchange) {
        return BindingBuilder.bind(customerEventsQueue)
                .to(fintechEventsExchange)
                .with("auth.#");
    }

    @Bean
    public MessageConverter jsonMessageConverter() {
        return new Jackson2JsonMessageConverter();
    }
}

