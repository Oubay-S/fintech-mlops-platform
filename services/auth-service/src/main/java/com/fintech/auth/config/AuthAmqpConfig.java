package com.fintech.auth.config;

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
public class AuthAmqpConfig {

    @Value("${app.messaging.exchange:fintech.events}")
    private String exchangeName;

    @Value("${app.messaging.queues.auth-events:auth.events}")
    private String queueName;

    @Bean
    public TopicExchange fintechEventsExchange() {
        return new TopicExchange(exchangeName, true, false);
    }

    @Bean
    public Queue authEventsQueue() {
        return new Queue(queueName, true);
    }

    @Bean
    public Binding bindingCustomerAccountStatusChanged(Queue authEventsQueue, TopicExchange fintechEventsExchange) {
        return BindingBuilder.bind(authEventsQueue)
                .to(fintechEventsExchange)
                .with("customer.account.*");
    }

    @Bean
    public MessageConverter jsonMessageConverter() {
        return new Jackson2JsonMessageConverter();
    }
}
