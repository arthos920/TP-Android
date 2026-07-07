# ============================================================
# AUDIO SELECTORS
# ============================================================

def _select_audio(self):
    """Open the audio type dropdown."""
    self.click_component(By.XPATH, _TYPE_SELECT_AUDIO)


def _select_audio_type_call(self):
    """Select the 'Call' audio type."""
    self._select_audio()
    self.click_component(By.XPATH, _TYPE_AUDIO_RADIO_CALL)


def _select_audio_type_conference(self):
    """Select the 'Conference' audio type."""
    self._select_audio()
    self.click_component(By.XPATH, _TYPE_AUDIO_RADIO_CONF)


def _select_audio_type_talk(self):
    """Select the 'Talk' audio type."""
    self._select_audio()
    self.click_component(By.XPATH, _TYPE_AUDIO_RADIO_TALK)


def _select_audio_type_ptt(self):
    """Select the 'PTT' audio type."""
    self._select_audio()
    self.click_component(By.XPATH, _TYPE_AUDIO_RADIO_PTT)


def _select_audio_type_emergency(self):
    """Select the 'Emergency' audio type."""
    self._select_audio()
    self.click_component(By.XPATH, _TYPE_AUDIO_RADIO_EMERGENCY)


def _select_audio_type_broadcast(self):
    """Select the 'Broadcast' audio type."""
    self._select_audio()
    self.click_component(By.XPATH, _TYPE_AUDIO_RADIO_BROADCAST)


# ============================================================
# VIDEO SELECTORS
# ============================================================

def _select_video(self):
    """Open the video type dropdown."""
    self.click_component(By.XPATH, _TYPE_SELECT_VIDEO)


def _select_video_type_call(self):
    """Select the 'Call' video type."""
    self._select_video()
    self.click_component(By.XPATH, _TYPE_VIDEO_RADIO_CALL)


def _select_video_type_streaming(self):
    """Select the 'Streaming' video type."""
    self._select_video()
    self.click_component(By.XPATH, _TYPE_VIDEO_RADIO_STREAM)


# ============================================================
# MEDIA SELECTORS
# ============================================================

def _select_media(self):
    """Open the media type dropdown."""
    self.click_component(By.XPATH, _TYPE_OPEN_SELECT)


def _select_media_type_message(self):
    """Select 'Message' media."""
    self._select_media()
    self.click_component(By.XPATH, _CHECKBOX_MESSAGE)


def _select_media_type_audio(self):
    """Select 'Audio' media."""
    self._select_media()
    self.click_component(By.XPATH, _CHECKBOX_AUDIO)


def _select_media_type_video(self):
    """Select 'Video' media."""
    self._select_media()
    self.click_component(By.XPATH, _CHECKBOX_VIDEO)