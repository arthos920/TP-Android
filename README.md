def assert_data_of_talkgroup_is_correctly_stored(
    self, group: Group, user_name_initiator: str,
    user_name_receiver: str
):
    self.open_audit_filter_menu()
    self._select_audio_type_talkgroup()
    self.filter_by_date_range()
    self.select_filter_type_talkgroup()
    self.filter_by_user(group.name)
    self.submit_filter()
    self._waiting_for_events(8)

    self.assert_talkgroup_event(
        group.name, user_name_initiator, AS_CONNECTED_EVENT_TYPE
    )
    self.assert_talkgroup_event(
        group.name, user_name_receiver, AS_CONNECTED_EVENT_TYPE
    )
    self.assert_talkgroup_event(
        group.name, user_name_initiator, AS_TAKE_FLOOR_EVENT_TYPE
    )
    self.assert_talkgroup_event(
        group.name, user_name_initiator, AS_RELEASED_EVENT_TYPE
    )
    self.assert_talkgroup_event(
        group.name, user_name_receiver, AS_TAKE_FLOOR_EVENT_TYPE
    )
    self.assert_talkgroup_event(
        group.name, user_name_receiver, AS_RELEASED_EVENT_TYPE
    )
    self.assert_talkgroup_event(
        group.name, user_name_initiator, AS_DISCONNECTED_EVENT_TYPE
    )
    self.assert_talkgroup_event(
        group.name, user_name_receiver, AS_DISCONNECTED_EVENT_TYPE
    )



def assert_talkgroup_event(self, group_name, user_name, event_type):
    self.assert_component_exists(
        By.XPATH,
        self.build_xpath()
        .element(data_report_type="audio-calls-channel")
        .descendant()
        .element(data_role="row-template")
        .has_child.all_of(
            self.build_xpath()
            .element(data_role="CallUuid", exact_text=group_name),

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