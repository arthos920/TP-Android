def assert_semi_duplex_event(self, call_uuid, user_name, event_type):
    self.assert_component_exists(
        By.XPATH,
        self.build_xpath()
        .element(data_report_type="audio-calls-ptt")
        .descendant()
        .element(data_role="row-template")
        .has_child.all_of(
            self.build_xpath()
            .element(data_role="CallUuid", exact_text=call_uuid),

            self.build_xpath()
            .element(data_role="EventOwner", exact_text=user_name),

            self.build_xpath()
            .element(data_role="EventType", exact_text=event_type)
        )
        .has_ancestor.none_of(
            self.build_xpath()
            .element(style_contains="display: none")
        )
    )


def get_semi_duplex_call_uuid(self, user_name):
    component = self.get_component(
        By.XPATH,
        self.build_xpath()
        .element(data_report_type="audio-calls-ptt")
        .descendant()
        .element(data_role="row-template")
        .has_child.all_of(
            self.build_xpath()
            .element(data_role="EventOwner", exact_text=user_name),

            self.build_xpath()
            .element(
                data_role="EventType",
                exact_text=AS_STARTED_EVENT_TYPE
            )
        )
        .has_ancestor.none_of(
            self.build_xpath()
            .element(style_contains="display: none")
        )
        .child()
        .element(data_role="CallUuid")
    )

    return component.text.strip()

def assert_data_of_semi_duplex_call_is_correctly_stored(
    self, user_name_initiator: str, user_name_receiver: str
):
    self.open_audit_filter_menu()
    self._select_audio_type_ptt()
    self.filter_by_date_range()
    self.filter_by_user(user_name_initiator)
    self.submit_filter()
    self._waiting_for_events(8)

    call_uuid = self.get_semi_duplex_call_uuid(
        user_name_initiator
    )

    self.assert_semi_duplex_event(
        call_uuid, user_name_initiator, AS_STARTED_EVENT_TYPE
    )
    self.assert_semi_duplex_event(
        call_uuid, user_name_receiver, AS_JOINED_EVENT_TYPE
    )
    self.assert_semi_duplex_event(
        call_uuid, user_name_initiator, AS_TAKE_FLOOR_EVENT_TYPE
    )
    self.assert_semi_duplex_event(
        call_uuid, user_name_initiator, AS_RELEASED_EVENT_TYPE
    )
    self.assert_semi_duplex_event(
        call_uuid, user_name_receiver, AS_TAKE_FLOOR_EVENT_TYPE
    )
    self.assert_semi_duplex_event(
        call_uuid, user_name_receiver, AS_RELEASED_EVENT_TYPE
    )
    self.assert_semi_duplex_event(
        call_uuid, user_name_initiator, AS_LEFT_EVENT_TYPE
    )
    self.assert_semi_duplex_event(
        call_uuid, user_name_receiver, AS_ENDED_EVENT_TYPE
    )